import type { Project } from "./types";
export type Category = "all" | "care" | "medical";
export function filterProjects(
  projects: Project[],
  category: Category,
  query = "",
) {
  const term = query.trim().toLowerCase();
  return projects.filter(
    (p) =>
      (category === "all" || p.category === category) &&
      `${p.title} ${p.topics.join(" ")} ${p.description}`
        .toLowerCase()
        .includes(term),
  );
}
