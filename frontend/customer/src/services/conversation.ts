import { ApiError, errorText, type ConsultationApi } from "./api";
import type {
  Answer,
  HistoryMessage,
  Message,
  PendingMessage,
  Project,
  PublicStore,
  Thread,
  VisitorSession,
} from "../types";

export class Conversation {
  session: VisitorSession | null = null;
  stores: PublicStore[] = [];
  threads: Thread[] = [];
  thread = "";
  projects: Project[] = [];
  messages: Message[] = [];
  pending: PendingMessage | null = null;
  busy = false;
  refreshing = false;
  ready = false;
  error = "";
  hasOlder = false;
  private offset = 0;
  constructor(
    private api: ConsultationApi,
    private storage?: Pick<Storage, "getItem" | "setItem" | "removeItem">,
  ) {}
  private remember() {
    try {
      this.storage?.setItem(
        "ma-consultation-reference",
        JSON.stringify({
          visitor_id: this.session?.visitor_id,
          thread_id: this.thread,
        }),
      );
    } catch {
      /* Optional reference only. */
    }
  }
  private remembered(): { visitor_id: string; thread_id: string } | null {
    try {
      return JSON.parse(
        this.storage?.getItem("ma-consultation-reference") ?? "null",
      );
    } catch {
      return null;
    }
  }
  private fail(error: unknown) {
    if (
      error instanceof ApiError &&
      (error.status === 401 ||
        error.code === "thread_not_found" ||
        error.code === "store_unavailable")
    ) {
      this.session = null;
      this.ready = false;
      this.thread = "";
      this.messages = [];
      this.projects = [];
      this.pending = null;
      this.threads = [];
      try {
        this.storage?.removeItem("ma-consultation-reference");
      } catch {
        /* Optional reference only. */
      }
    }
    this.error = errorText(error);
  }
  private applyHistory(rows: HistoryMessage[], older = false) {
    const converted = rows.map((row) => ({
      id: row.id,
      message_id: row.message_id,
      role: row.role,
      text: row.content,
      result: row.role === "assistant" ? (row.result ?? undefined) : undefined,
    }));
    this.messages = older
      ? [...converted, ...this.messages].filter(
          (row, index, all) =>
            all.findIndex((item) => item.id === row.id) === index,
        )
      : converted;
    this.offset = older ? this.offset + rows.length : rows.length;
    this.hasOlder = rows.length === 100;
    if (!older) {
      const last = rows.at(-1);
      this.pending =
        last?.role === "user" && last.status !== "completed"
          ? { message_id: last.message_id, question: last.content }
          : null;
      if (this.pending) this.error = "这条消息尚未完成，请核实并重试原消息。";
    }
  }
  async initialize(entryStore?: string) {
    if (this.busy || this.refreshing) return;
    this.busy = true;
    this.error = "";
    this.ready = false;
    try {
      this.stores = await this.api.stores();
      try {
        this.session = await this.api.current();
      } catch (error) {
        if (!(error instanceof ApiError) || error.status !== 401) throw error;
        if (this.remembered()) throw error;
        const code = entryStore || this.stores[0]?.code;
        if (!code) throw new ApiError("no_public_store");
        await this.api.createSession(code);
        this.session = await this.api.current();
      }
      const [projects, threads] = await Promise.all([
        this.api.projects(),
        this.api.threads(),
      ]);
      this.projects = projects;
      this.threads = threads;
      const reference = this.remembered();
      this.thread =
        reference?.visitor_id === this.session.visitor_id
          ? reference.thread_id
          : (threads[0]?.thread_id ?? "");
      if (!this.thread) this.thread = await this.api.newThread();
      try {
        this.applyHistory(await this.api.history(this.thread));
      } catch (error) {
        if (!(error instanceof ApiError) || error.status !== 404) throw error;
        this.thread = threads[0]?.thread_id ?? (await this.api.newThread());
        this.applyHistory(await this.api.history(this.thread));
      }
      this.threads = await this.api.threads();
      this.remember();
      this.ready = true;
    } catch (error) {
      this.fail(error);
    } finally {
      this.busy = false;
    }
  }
  async send(question: string) {
    const trimmed = question.trim();
    if (
      !this.ready ||
      this.busy ||
      this.refreshing ||
      this.pending ||
      !trimmed ||
      trimmed.length > 2000
    )
      return;
    this.pending = { message_id: crypto.randomUUID(), question: trimmed };
    this.messages.push({
      id: this.pending.message_id,
      message_id: this.pending.message_id,
      role: "user",
      text: trimmed,
    });
    await this.retry();
  }
  async retry() {
    if (!this.ready || this.busy || this.refreshing || !this.pending) return;
    this.busy = true;
    this.error = "";
    const message = { ...this.pending };
    try {
      this.accept(await this.api.send(this.thread, message), message);
    } catch (error) {
      this.fail(error);
    } finally {
      this.busy = false;
    }
  }
  private accept(result: Answer, message: PendingMessage) {
    this.messages = this.messages.filter(
      (row) => row.message_id !== message.message_id,
    );
    this.messages.push(
      {
        id: message.message_id,
        message_id: message.message_id,
        role: "user",
        text: message.question,
      },
      {
        id: result.run_id,
        message_id: message.message_id,
        role: "assistant",
        text: result.answer,
        result,
      },
    );
    this.pending = null;
  }
  async refresh() {
    if (!this.ready || this.busy || this.refreshing) return;
    this.refreshing = true;
    this.error = "";
    try {
      const session = await this.api.current();
      if (session.visitor_id !== this.session?.visitor_id)
        throw new ApiError("unauthenticated", 401);
      this.session = session;
      const [projects, rows] = await Promise.all([
        this.api.projects(),
        this.api.history(this.thread),
      ]);
      this.projects = projects;
      this.applyHistory(rows);
    } catch (error) {
      this.projects = [];
      this.messages = this.messages.map((row) =>
        row.role === "assistant"
          ? {
              ...row,
              text: "此回答需要重新校验证据，请刷新后查看。",
              result: undefined,
            }
          : row,
      );
      this.fail(error);
    } finally {
      this.refreshing = false;
    }
  }
  async older() {
    if (!this.ready || this.busy || this.refreshing || !this.hasOlder) return;
    this.busy = true;
    try {
      this.applyHistory(await this.api.history(this.thread, this.offset), true);
    } catch (error) {
      this.fail(error);
    } finally {
      this.busy = false;
    }
  }
  async selectThread(thread: string) {
    if (this.busy || this.refreshing || !this.ready || thread === this.thread)
      return;
    this.busy = true;
    this.error = "";
    try {
      const rows = await this.api.history(thread);
      this.thread = thread;
      this.applyHistory(rows);
      this.remember();
    } catch (error) {
      this.fail(error);
    } finally {
      this.busy = false;
    }
  }
  async newConversation() {
    if (this.busy || this.refreshing || !this.ready) return;
    this.busy = true;
    this.error = "";
    try {
      this.thread = await this.api.newThread();
      this.messages = [];
      this.pending = null;
      this.hasOlder = false;
      this.offset = 0;
      this.threads = await this.api.threads();
      this.remember();
    } catch (error) {
      this.fail(error);
    } finally {
      this.busy = false;
    }
  }
  async switchStore(code: string) {
    if (
      this.busy ||
      this.refreshing ||
      !this.ready ||
      code === this.session?.store_code
    )
      return;
    this.busy = true;
    this.error = "";
    this.ready = false;
    this.messages = [];
    this.projects = [];
    this.pending = null;
    try {
      await this.api.createSession(code);
      this.session = await this.api.current();
      this.thread = await this.api.newThread();
      this.projects = await this.api.projects();
      this.threads = await this.api.threads();
      this.remember();
      this.ready = true;
    } catch (error) {
      this.fail(error);
    } finally {
      this.busy = false;
    }
  }
}
