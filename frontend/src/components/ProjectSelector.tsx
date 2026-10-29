"use client";

import React, { useState } from "react";
import type { ProjectSummary } from "@/lib/api";

interface ProjectSelectorProps {
  candidateId: string;
  projects: ProjectSummary[];
  selectedProjectId: string | null;
  onSelectProject: (projectId: string) => Promise<void>;
  loading?: boolean;
}

const KNOWN_TECH_KEYWORDS = [
  "Python", "FastAPI", "Django", "Flask", "React", "Next.js", "Node.js", "Express",
  "TypeScript", "JavaScript", "Rust", "Go", "Golang", "C++", "Java", "Kotlin", "Swift",
  "Flutter", "Docker", "Kubernetes", "AWS", "AWS S3", "S3", "PostgreSQL", "Postgres",
  "MySQL", "SQLite", "Redis", "ChromaDB", "BM25", "Groq", "Llama", "Llama 3.3",
  "LangChain", "PyTorch", "TensorFlow", "Tailwind CSS", "Tailwind", "GraphQL",
  "REST", "MongoDB", "Celery", "Laravel", "Vue", "Angular", "Linux"
];

function extractTechnologies(text: string): string[] {
  if (!text) return [];
  const found: string[] = [];
  const lower = text.toLowerCase();
  for (const kw of KNOWN_TECH_KEYWORDS) {
    // Word boundary match
    const escaped = kw.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const regex = new RegExp(`(?:^|[^a-zA-Z0-9_])${escaped}(?:[^a-zA-Z0-9_]|$)`, "i");
    if (regex.test(text)) {
      found.push(kw);
    }
  }
  return Array.from(new Set(found));
}

export function ProjectSelector({
  projects,
  selectedProjectId,
  onSelectProject,
  loading = false,
}: ProjectSelectorProps) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editedProjects, setEditedProjects] = useState<Record<string, { name: string; description: string }>>({});
  const [manualProjects, setManualProjects] = useState<ProjectSummary[]>([]);
  const [isAddingManual, setIsAddingManual] = useState<boolean>(false);
  const [manualName, setManualName] = useState<string>("");
  const [manualDescription, setManualDescription] = useState<string>("");
  const [manualUrl, setManualUrl] = useState<string>("");

  const allProjects = [...projects, ...manualProjects];

  const handleStartEdit = (proj: ProjectSummary) => {
    setEditingId(proj.id);
    if (!editedProjects[proj.id]) {
      setEditedProjects((prev) => ({
        ...prev,
        [proj.id]: {
          name: proj.name,
          description: proj.description || "",
        },
      }));
    }
  };

  const handleSaveEdit = (projId: string) => {
    setEditingId(null);
  };

  const handleAddManualProject = (e: React.FormEvent) => {
    e.preventDefault();
    if (!manualName.trim()) return;

    const newProj: ProjectSummary = {
      id: `manual-${Date.now()}`,
      candidateId: "",
      name: manualName.trim(),
      description: manualDescription.trim() || null,
      isSelected: false,
      explicitGithubUrls: manualUrl.trim() ? [manualUrl.trim()] : [],
      createdAt: new Date().toISOString(),
    };

    setManualProjects((prev) => [...prev, newProj]);
    setManualName("");
    setManualDescription("");
    setManualUrl("");
    setIsAddingManual(false);
  };

  return (
    <section className="mb-10" data-purpose="step-1-project-selection">
      {/* Step Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-3 mb-4 border-b border-slate-200">
        <div>
          <div className="text-xs uppercase font-bold tracking-wider text-slate-400">Step 1</div>
          <h2 className="text-xl font-bold text-slate-900">1. Select Review Project</h2>
          <p className="text-sm text-slate-500 mt-0.5">
            Select exactly one project to confirm repository candidates and execute analysis.
          </p>
        </div>
        <div className="mt-3 sm:mt-0">
          <button
            type="button"
            onClick={() => setIsAddingManual((prev) => !prev)}
            className="inline-flex items-center text-xs font-semibold px-3 py-2 rounded-lg bg-white border border-slate-300 text-slate-700 hover:bg-slate-50 shadow-xs transition"
          >
            <svg className="w-3.5 h-3.5 mr-1.5 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path d="M12 4v16m8-8H4" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" />
            </svg>
            {isAddingManual ? "Cancel Manual Project" : "+ Add Manual Project"}
          </button>
        </div>
      </div>

      {/* Manual Entry Form */}
      {isAddingManual && (
        <form
          onSubmit={handleAddManualProject}
          className="mb-5 p-5 bg-white border border-slate-300 rounded-xl shadow-xs text-xs space-y-3.5"
        >
          <div className="font-semibold text-slate-900 text-sm">Add Manual Project Entry</div>
          <div>
            <label htmlFor="manual-name" className="block text-slate-700 font-medium mb-1">
              Project Name *
            </label>
            <input
              id="manual-name"
              type="text"
              value={manualName}
              onChange={(e) => setManualName(e.target.value)}
              required
              className="w-full border border-slate-300 rounded-lg p-2 text-slate-900 focus:ring-1 focus:ring-slate-900 focus:border-slate-900"
              placeholder="e.g. Distributed Key-Value Store"
            />
          </div>
          <div>
            <label htmlFor="manual-desc" className="block text-slate-700 font-medium mb-1">
              Description
            </label>
            <textarea
              id="manual-desc"
              value={manualDescription}
              onChange={(e) => setManualDescription(e.target.value)}
              className="w-full border border-slate-300 rounded-lg p-2 text-slate-900 focus:ring-1 focus:ring-slate-900 focus:border-slate-900"
              placeholder="Brief summary of candidate's project work and technical stack"
              rows={3}
            />
          </div>
          <div>
            <label htmlFor="manual-url" className="block text-slate-700 font-medium mb-1">
              Declared GitHub URL (Optional)
            </label>
            <input
              id="manual-url"
              type="url"
              value={manualUrl}
              onChange={(e) => setManualUrl(e.target.value)}
              className="w-full border border-slate-300 rounded-lg p-2 font-mono text-slate-900 focus:ring-1 focus:ring-slate-900 focus:border-slate-900"
              placeholder="https://github.com/candidate/repo"
            />
          </div>
          <div className="flex gap-2">
            <button
              type="submit"
              className="px-4 py-2 bg-slate-900 hover:bg-slate-800 text-white rounded-lg font-medium text-xs shadow-xs"
            >
              Save Project
            </button>
            <button
              type="button"
              onClick={() => setIsAddingManual(false)}
              className="px-3 py-2 border border-slate-300 text-slate-600 rounded-lg hover:bg-slate-50 font-medium text-xs"
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      {/* Projects List with Radio Selection */}
      {allProjects.length === 0 ? (
        <div className="text-center py-8 bg-white border border-dashed border-slate-300 rounded-xl text-xs text-slate-500">
          No projects available. Click &quot;+ Add Manual Project&quot; above to create one.
        </div>
      ) : (
        <div
          role="radiogroup"
          aria-label="Candidate Project Selection"
          className="space-y-4"
        >
          {allProjects.map((proj) => {
            const isSelected = selectedProjectId === proj.id;
            const isEditing = editingId === proj.id;
            const currentName = editedProjects[proj.id]?.name ?? proj.name;
            const currentDesc = editedProjects[proj.id]?.description ?? (proj.description || "");
            const detectedTech = extractTechnologies(`${currentName} ${currentDesc}`);

            return (
              <label
                key={proj.id}
                htmlFor={`proj-radio-${proj.id}`}
                className={`relative flex flex-col md:flex-row md:items-start justify-between p-5 rounded-xl cursor-pointer transition-all ${
                  isSelected
                    ? "border-2 border-slate-900 bg-white shadow-md ring-1 ring-slate-900/10"
                    : "border border-slate-200 bg-white hover:border-slate-300 shadow-xs"
                }`}
              >
                <div className="flex items-start gap-4 flex-1">
                  <input
                    type="radio"
                    id={`proj-radio-${proj.id}`}
                    name="candidate-project-selection"
                    checked={isSelected}
                    disabled={loading}
                    onChange={() => onSelectProject(proj.id)}
                    className="mt-1 h-4 w-4 text-slate-900 border-slate-300 focus:ring-slate-900 cursor-pointer"
                  />
                  <div className="flex-1">
                    {isEditing ? (
                      <div className="space-y-2.5 mt-1" onClick={(e) => e.stopPropagation()}>
                        <input
                          type="text"
                          value={currentName}
                          onChange={(e) =>
                            setEditedProjects((prev) => ({
                              ...prev,
                              [proj.id]: { ...prev[proj.id], name: e.target.value },
                            }))
                          }
                          className="w-full border border-slate-300 rounded-lg p-2 text-sm font-semibold text-slate-900"
                        />
                        <textarea
                          value={currentDesc}
                          onChange={(e) =>
                            setEditedProjects((prev) => ({
                              ...prev,
                              [proj.id]: { ...prev[proj.id], description: e.target.value },
                            }))
                          }
                          className="w-full border border-slate-300 rounded-lg p-2 text-xs text-slate-700"
                          rows={3}
                        />
                        <div className="flex gap-2">
                          <button
                            type="button"
                            onClick={() => handleSaveEdit(proj.id)}
                            className="px-3 py-1.5 bg-slate-900 hover:bg-slate-800 text-white rounded-lg text-xs font-semibold"
                          >
                            Done Editing
                          </button>
                        </div>
                      </div>
                    ) : (
                      <div>
                        {/* Title & Badges */}
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-bold text-slate-900 text-base">
                            {currentName}
                          </span>
                          {isSelected && (
                            <span className="inline-flex items-center text-[11px] font-semibold px-2 py-0.5 rounded bg-slate-900 text-white">
                              <svg className="w-3 h-3 mr-1" fill="currentColor" viewBox="0 0 20 20">
                                <path
                                  fillRule="evenodd"
                                  d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z"
                                  clipRule="evenodd"
                                />
                              </svg>
                              Target Project
                            </span>
                          )}
                        </div>

                        {/* Description */}
                        {currentDesc && (
                          <div className="mt-2 text-sm text-slate-600 leading-relaxed space-y-1.5">
                            {currentDesc.split("\n\n").map((para, idx) => (
                              <p key={idx}>{para}</p>
                            ))}
                          </div>
                        )}

                        {/* Technologies */}
                        {detectedTech.length > 0 && (
                          <div className="mt-3.5 flex flex-wrap items-center gap-1.5">
                            <span className="text-xs font-medium text-slate-400 mr-1">
                              Technologies:
                            </span>
                            {detectedTech.map((tech, i) => (
                              <span
                                key={tech}
                                className={`px-2 py-0.5 text-xs rounded font-medium ${
                                  i === 0 && isSelected
                                    ? "bg-slate-900 text-white"
                                    : "bg-slate-100 text-slate-700"
                                }`}
                              >
                                {tech}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    )}

                    {/* Display Extracted Resume Links Separately */}
                    {proj.explicitGithubUrls && proj.explicitGithubUrls.length > 0 && (
                      <div className="mt-3.5 pt-3 border-t border-slate-100">
                        <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 block mb-1.5">
                          Extracted Resume Link:
                        </span>
                        <div className="flex flex-wrap gap-2">
                          {proj.explicitGithubUrls.map((url, i) => (
                            <a
                              key={i}
                              href={url}
                              target="_blank"
                              rel="noopener noreferrer"
                              onClick={(e) => e.stopPropagation()}
                              className="text-xs text-blue-600 hover:underline font-mono bg-slate-100 hover:bg-slate-200 px-2.5 py-1 rounded-md border border-slate-200 inline-flex items-center gap-1.5"
                            >
                              <span>{url}</span>
                              <svg className="w-3 h-3 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" />
                              </svg>
                            </a>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                </div>

                {!isEditing && (
                  <div className="mt-3 md:mt-0 flex-shrink-0 self-end md:self-start">
                    <button
                      type="button"
                      onClick={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        handleStartEdit(proj);
                      }}
                      className="inline-flex items-center text-xs font-medium text-slate-600 hover:text-slate-900 bg-slate-100 hover:bg-slate-200 px-2.5 py-1 rounded-md transition"
                    >
                      <svg className="w-3.5 h-3.5 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" />
                      </svg>
                      Edit
                    </button>
                  </div>
                )}
              </label>
            );
          })}
        </div>
      )}
    </section>
  );
}
