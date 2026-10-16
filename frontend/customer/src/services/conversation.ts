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
  customer: { username: string } | null = null;
  freshSession = false;
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
  hasMoreThreads = false;
  loadingThreads = false;
  threadListError = "";
  private offset = 0;
  private threadOffset = 0;
  private threadListVersion = 0;
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
  private applyThreads(rows: Thread[], append = false) {
    if (!append) {
      this.threadListVersion++;
      this.loadingThreads = false;
    }
    this.threads = (append ? [...this.threads, ...rows] : rows).filter(
      (row, index, all) =>
        all.findIndex((item) => item.thread_id === row.thread_id) === index,
    );
    this.threadOffset = append ? this.threadOffset + rows.length : rows.length;
    this.hasMoreThreads = rows.length === 20;
    this.threadListError = "";
  }
  private fail(error: unknown) {
    if (
      error instanceof ApiError &&
      (error.status === 401 ||
        error.code === "thread_not_found" ||
        error.code === "store_unavailable")
    ) {
      this.session = null;
      this.customer = null;
      this.ready = false;
      this.thread = "";
      this.messages = [];
      this.projects = [];
      this.pending = null;
      this.threads = [];
      this.hasMoreThreads = false;
      this.loadingThreads = false;
      this.threadListVersion++;
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
    this.freshSession = false;
    this.error = "";
    this.ready = false;
    try {
      this.stores = await this.api.stores();
      try {
        this.session = await this.api.current();
      } catch (error) {
        if (!(error instanceof ApiError) || error.status !== 401) throw error;
        const code = entryStore || this.stores[0]?.code;
        if (!code) throw new ApiError("no_public_store");
        await this.api.createSession(code);
        this.session = await this.api.current();
        this.freshSession = !entryStore;
      }
      const identity = await this.api.customerSession();
      this.customer = identity.customer;
      if (!this.customer) {
        this.thread = "";
        this.messages = [];
        this.pending = null;
        this.projects = [];
        this.threads = [];
        return;
      }
      const [projects, threads] = await Promise.all([
        this.api.projects(),
        this.api.threads(),
      ]);
      this.projects = projects;
      this.applyThreads(threads);
      // The server lists this customer's threads newest first. A browser reference
      // may point to an older conversation created before another device signed in.
      this.thread = threads[0]?.thread_id ?? "";
      if (!this.thread) this.thread = await this.api.newThread();
      try {
        this.applyHistory(await this.api.history(this.thread));
      } catch (error) {
        if (!(error instanceof ApiError) || error.status !== 404) throw error;
        const latest = await this.api.threads();
        this.thread = latest[0]?.thread_id ?? (await this.api.newThread());
        this.applyHistory(await this.api.history(this.thread));
      }
      this.applyThreads(await this.api.threads());
      this.remember();
      this.ready = true;
    } catch (error) {
      this.fail(error);
    } finally {
      this.busy = false;
    }
  }
  clearIdentity() {
    this.freshSession = false;
    this.customer = null;
    this.ready = false;
    this.session = null;
    this.thread = "";
    this.messages = [];
    this.pending = null;
    this.threads = [];
    this.hasMoreThreads = false;
    this.loadingThreads = false;
    this.threadListError = "";
    this.threadListVersion++;
    this.projects = [];
    this.hasOlder = false;
    try {
      this.storage?.removeItem("ma-consultation-reference");
    } catch {
      /* Optional. */
    }
  }
  async reloadIdentity(entryStore?: string) {
    if (this.busy || this.refreshing) return;
    this.clearIdentity();
    await this.initialize(entryStore);
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
    if (!this.messages.length) {
      this.threads = this.threads.map((row) =>
        row.thread_id === this.thread
          ? {
              ...row,
              title: Array.from(trimmed.replace(/\s+/g, " "))
                .slice(0, 24)
                .join(""),
            }
          : row,
      );
    }
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
        animate: true,
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
      const hadMore = this.hasMoreThreads;
      this.applyThreads([
        {
          thread_id: this.thread,
          title: "新对话",
          created_at: new Date().toISOString(),
        },
        ...this.threads,
      ]);
      this.hasMoreThreads = hadMore;
      this.remember();
      // Creating the thread already succeeded; a list refresh failure must not
      // lose the new ID or invite a second creation attempt.
      try {
        this.applyThreads(await this.api.threads());
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) throw error;
        this.threadListError = "会话已创建，列表暂未刷新，请稍后重试。";
      }
    } catch (error) {
      this.fail(error);
    } finally {
      this.busy = false;
    }
  }
  async selectThread(thread: string) {
    if (!this.ready || this.busy || this.refreshing || thread === this.thread)
      return;
    this.busy = true;
    this.error = "";
    try {
      const rows = await this.api.history(thread);
      this.thread = thread;
      this.applyHistory(rows);
      this.remember();
    } catch (error) {
      if (error instanceof ApiError && error.status === 404)
        this.error = "这段对话暂时无法打开，请刷新页面后重试。";
      else this.fail(error);
    } finally {
      this.busy = false;
    }
  }
  async moreThreads() {
    if (
      !this.ready ||
      this.busy ||
      this.refreshing ||
      this.loadingThreads ||
      !this.hasMoreThreads
    )
      return;
    const visitor = this.session?.visitor_id;
    const version = this.threadListVersion;
    this.loadingThreads = true;
    this.threadListError = "";
    try {
      const rows = await this.api.threads(this.threadOffset);
      if (
        visitor === this.session?.visitor_id &&
        version === this.threadListVersion
      )
        this.applyThreads(rows, true);
    } catch (error) {
      if (
        visitor === this.session?.visitor_id &&
        version === this.threadListVersion
      ) {
        if (error instanceof ApiError && error.status === 401) this.fail(error);
        else this.threadListError = "历史会话暂未加载成功，请重试。";
      }
    } finally {
      if (version === this.threadListVersion) this.loadingThreads = false;
    }
  }
  async switchStore(code: string) {
    if (this.busy || this.refreshing || code === this.session?.store_code)
      return;
    this.busy = true;
    this.error = "";
    this.ready = false;
    this.messages = [];
    this.projects = [];
    this.pending = null;
    try {
      await this.api.createSession(code);
      this.clearIdentity();
      this.session = await this.api.current();
    } catch (error) {
      this.fail(error);
    } finally {
      this.busy = false;
    }
  }
}
