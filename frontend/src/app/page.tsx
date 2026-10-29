"use client";

import React, { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ResumeUpload } from "@/components/ResumeUpload";
import { useSession } from "@/components/SessionProvider";
import {
  deleteCandidate,
  getCandidate,
  listCandidates,
  selectCandidateProject,
  type CandidateDetailResponse,
  type CandidateSummary,
} from "@/lib/api";

export default function DashboardPage() {
  const router = useRouter();
  const { logout } = useSession();

  const [candidates, setCandidates] = useState<CandidateSummary[]>([]);
  const [selectedCandidate, setSelectedCandidate] = useState<CandidateDetailResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [candidateDetailLoading, setCandidateDetailLoading] = useState<boolean>(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [showManualModal, setShowManualModal] = useState<boolean>(false);

  const fetchCandidates = useCallback(async () => {
    setLoading(true);
    setActionError(null);
    try {
      const data = await listCandidates();
      setCandidates(data);
      if (selectedCandidate) {
        // Refresh currently viewed candidate
        const updated = await getCandidate(selectedCandidate.id);
        setSelectedCandidate(updated);
      }
    } catch (err: unknown) {
      if (err instanceof Error) {
        setActionError(err.message);
      }
    } finally {
      setLoading(false);
    }
  }, [selectedCandidate]);

  useEffect(() => {
    fetchCandidates();
  }, []);

  const handleSelectCandidateToView = async (candidateId: string) => {
    setCandidateDetailLoading(true);
    setActionError(null);
    try {
      const detail = await getCandidate(candidateId);
      setSelectedCandidate(detail);
    } catch (err: unknown) {
      if (err instanceof Error) {
        setActionError(err.message);
      }
    } finally {
      setCandidateDetailLoading(false);
    }
  };

  const handleSelectPrimaryProject = async (candidateId: string, projectId: string) => {
    setActionError(null);
    try {
      const updated = await selectCandidateProject(candidateId, projectId);
      setSelectedCandidate(updated);
      await fetchCandidates();
    } catch (err: unknown) {
      if (err instanceof Error) {
        setActionError(err.message);
      }
    }
  };

  const handleDeleteCandidate = async (candidateId: string) => {
    if (!window.confirm("Are you sure you want to delete this candidate and all associated files?")) {
      return;
    }
    setActionError(null);
    try {
      await deleteCandidate(candidateId);
      if (selectedCandidate && selectedCandidate.id === candidateId) {
        setSelectedCandidate(null);
      }
      await fetchCandidates();
    } catch (err: unknown) {
      if (err instanceof Error) {
        setActionError(err.message);
      }
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 flex flex-col">
      {/* Top Header */}
      <header className="bg-white border-b border-slate-200 sticky top-0 z-30">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded bg-blue-600 flex items-center justify-center text-white font-bold text-sm">
              HR
            </div>
            <div>
              <h1 className="text-base font-semibold text-slate-900 leading-tight">
                Resume Review Platform
              </h1>
              <span className="text-xs text-slate-500 font-normal">
                Evidence-Based Candidate Verification
              </span>
            </div>
          </div>

          <div className="flex items-center gap-4">
            <span className="text-xs bg-slate-100 text-slate-700 px-2.5 py-1 rounded font-medium border border-slate-200">
              Admin Mode
            </span>
            <button
              onClick={() => logout()}
              className="text-xs font-medium text-slate-600 hover:text-slate-900 px-3 py-1.5 border border-slate-300 rounded hover:bg-slate-50 transition-colors"
            >
              Sign Out
            </button>
          </div>
        </div>
      </header>

      {/* Main Content Area */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 flex-1 w-full">
        {actionError && (
          <div
            role="alert"
            className="mb-6 p-4 bg-red-50 border border-red-200 rounded-md text-sm text-red-800 flex items-center justify-between"
          >
            <span>{actionError}</span>
            <button
              onClick={() => setActionError(null)}
              className="text-xs text-red-600 font-bold hover:underline"
            >
              Dismiss
            </button>
          </div>
        )}

        {/* 1. Resume Multi-Upload Component */}
        <ResumeUpload
          onUploadComplete={fetchCandidates}
          onManualEntryClick={() => setShowManualModal(true)}
        />

        {/* 2. Candidate Profiles & Project Selection */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
          {/* Candidates List Column */}
          <div className="lg:col-span-1 bg-white rounded-lg border border-slate-200 shadow-sm p-5">
            <div className="flex items-center justify-between mb-4 pb-3 border-b border-slate-100">
              <h2 className="text-base font-semibold text-slate-800">
                Candidates ({candidates.length})
              </h2>
              <button
                onClick={fetchCandidates}
                disabled={loading}
                className="text-xs text-blue-600 hover:text-blue-800 font-medium disabled:opacity-50"
              >
                {loading ? "Refreshing..." : "Refresh"}
              </button>
            </div>

            {loading && candidates.length === 0 ? (
              <div className="p-8 text-center text-sm text-slate-400">
                Loading candidate profiles...
              </div>
            ) : candidates.length === 0 ? (
              <div className="p-8 text-center text-sm text-slate-500">
                No candidates uploaded yet. Upload a batch of resumes above to begin.
              </div>
            ) : (
              <ul className="divide-y divide-slate-100 space-y-2">
                {candidates.map((c) => {
                  const isCurrent = selectedCandidate?.id === c.id;
                  const hasSelectedProject = Boolean(c.selectedProjectId);

                  return (
                    <li
                      key={c.id}
                      onClick={() => handleSelectCandidateToView(c.id)}
                      className={`p-3 rounded-md cursor-pointer transition-colors border ${
                        isCurrent
                          ? "bg-blue-50/70 border-blue-300"
                          : "hover:bg-slate-50 border-transparent"
                      }`}
                    >
                      <div className="flex items-start justify-between">
                        <div>
                          <div className="font-medium text-slate-900 text-sm">
                            {c.name}
                          </div>
                          {c.email && (
                            <div className="text-xs text-slate-500">{c.email}</div>
                          )}
                        </div>
                        <span
                          className={`text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded-full ${
                            hasSelectedProject
                              ? "bg-green-100 text-green-800"
                              : "bg-amber-100 text-amber-800"
                          }`}
                        >
                          {hasSelectedProject ? "Project Selected" : "Needs Selection"}
                        </span>
                      </div>
                      <div className="mt-2 flex items-center justify-between text-xs text-slate-400">
                        <span>{c.projectsCount} project(s) extracted</span>
                        <div className="flex items-center gap-2">
                          <Link
                            href={`/candidates/${c.id}`}
                            onClick={(e) => e.stopPropagation()}
                            className="text-xs font-semibold text-blue-600 hover:text-blue-800"
                          >
                            Review →
                          </Link>
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              handleDeleteCandidate(c.id);
                            }}
                            className="text-red-500 hover:text-red-700"
                            aria-label={`Delete candidate ${c.name}`}
                          >
                            Delete
                          </button>
                        </div>
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>

          {/* Candidate Detail & Project Selection Column */}
          <div className="lg:col-span-2 bg-white rounded-lg border border-slate-200 shadow-sm p-6">
            {candidateDetailLoading ? (
              <div className="p-12 text-center text-sm text-slate-400">
                Loading candidate details...
              </div>
            ) : !selectedCandidate ? (
              <div className="p-12 text-center text-slate-500">
                <div className="text-base font-medium text-slate-700 mb-1">
                  No Candidate Selected
                </div>
                <p className="text-xs text-slate-400">
                  Select a candidate from the left to inspect extracted projects and select one for repository review.
                </p>
              </div>
            ) : (
              <div className="space-y-6">
                {/* Candidate Header */}
                <div className="border-b border-slate-100 pb-4 flex items-start justify-between">
                  <div>
                    <h2 className="text-xl font-bold text-slate-900">
                      {selectedCandidate.name}
                    </h2>
                    <p className="text-xs text-slate-500 mt-0.5">
                      {selectedCandidate.email || "No email detected"} • Uploaded {new Date(selectedCandidate.createdAt).toLocaleDateString()}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <Link
                      href={`/candidates/${selectedCandidate.id}`}
                      className="text-xs text-blue-700 bg-blue-50 border border-blue-200 hover:bg-blue-100 px-3 py-1.5 rounded font-medium transition-colors"
                    >
                      Review & Run Analysis →
                    </Link>
                    <button
                      onClick={() => handleDeleteCandidate(selectedCandidate.id)}
                      className="text-xs text-red-600 hover:text-red-800 border border-red-200 bg-red-50 px-3 py-1.5 rounded font-medium"
                    >
                      Delete Candidate
                    </button>
                  </div>
                </div>

                {/* Mandated Project Selection Notice or Next Steps Banner */}
                {!selectedCandidate.selectedProjectId ? (
                  <div
                    role="alert"
                    className="p-4 bg-amber-50 border border-amber-300 rounded-md text-amber-900 text-sm"
                  >
                    <div className="font-semibold mb-1">
                      ⚠️ Project Selection Required
                    </div>
                    <p className="text-xs text-amber-800">
                      To proceed with public repository analysis, select exactly one primary project below for evaluation.
                    </p>
                  </div>
                ) : (
                  <div
                    role="region"
                    className="p-4 bg-green-50 border border-green-300 rounded-md text-green-950 text-sm flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 shadow-sm"
                  >
                    <div>
                      <div className="font-semibold text-green-900 flex items-center gap-1.5">
                        <span className="text-green-700 text-base">✓</span> Primary Project Selected
                      </div>
                      <p className="text-xs text-green-800 mt-0.5">
                        Next step: Match and confirm the candidate&apos;s GitHub repository, then run the evidence analysis.
                      </p>
                    </div>
                    <Link
                      href={`/candidates/${selectedCandidate.id}`}
                      className="px-4 py-2 bg-green-700 hover:bg-green-800 text-white rounded text-xs font-semibold shadow-sm inline-flex items-center justify-center gap-1.5 transition-colors whitespace-nowrap"
                    >
                      Proceed to Repository Review →
                    </Link>
                  </div>
                )}

                {/* Projects List */}
                <div>
                  <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-600 mb-3">
                    Extracted Projects ({(selectedCandidate.projects || []).length})
                  </h3>

                  {(selectedCandidate.projects || []).length === 0 ? (
                    <div className="p-6 bg-slate-50 border border-dashed border-slate-200 rounded-md text-center text-xs text-slate-500">
                      No projects were automatically extracted from this resume. You can enter project details manually.
                    </div>
                  ) : (
                    <div className="space-y-3">
                      {(selectedCandidate.projects || []).map((proj) => {
                        const isSelected = selectedCandidate.selectedProjectId === proj.id;
                        const githubUrl = proj.explicitGithubUrls?.[0];

                        return (
                          <div
                            key={proj.id}
                            className={`p-4 rounded-md border transition-all ${
                              isSelected
                                ? "bg-blue-50/50 border-blue-400 shadow-sm"
                                : "bg-white border-slate-200 hover:border-slate-300"
                            }`}
                          >
                            <div className="flex items-start justify-between">
                              <div>
                                <h4 className="font-semibold text-slate-900 text-base">
                                  {proj.name}
                                </h4>
                                {proj.description && (
                                  <p className="text-xs text-slate-600 mt-1 leading-relaxed">
                                    {proj.description}
                                  </p>
                                )}
                              </div>

                              <button
                                type="button"
                                onClick={() =>
                                  handleSelectPrimaryProject(selectedCandidate.id, proj.id)
                                }
                                className={`text-xs px-3 py-1.5 rounded font-semibold transition-colors ${
                                  isSelected
                                    ? "bg-blue-600 text-white cursor-default"
                                    : "bg-slate-100 hover:bg-slate-200 text-slate-700 border border-slate-300"
                                }`}
                              >
                                {isSelected ? "✓ Selected Project" : "Select as Primary"}
                              </button>
                            </div>

                            {/* Declared Repository */}
                            {githubUrl && (
                              <div className="mt-3 pt-2 border-t border-slate-100">
                                <a
                                  href={githubUrl}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="text-xs text-blue-600 hover:underline flex items-center gap-1 font-mono"
                                >
                                  🔗 {githubUrl}
                                </a>
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>

                {/* Resumes List */}
                <div className="border-t border-slate-100 pt-4">
                  <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-2">
                    Source Document
                  </h3>
                  <ul className="text-xs text-slate-600 space-y-1">
                    {(selectedCandidate.resumes || []).map((r) => (
                      <li key={r.id} className="flex items-center gap-2">
                        📄 <span className="font-mono">{r.originalFilename}</span>{" "}
                        {r.fileSizeBytes ? `(${(r.fileSizeBytes / 1024).toFixed(1)} KB)` : ""}
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            )}
          </div>
        </div>
      </main>

      {/* Manual Entry Modal Dialog */}
      {showManualModal && (
        <div
          role="dialog"
          aria-modal="true"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
        >
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full p-6">
            <h3 className="text-lg font-bold text-slate-900 mb-2">
              Manual Candidate & Project Entry
            </h3>
            <p className="text-xs text-slate-600 mb-4">
              For scanned or non-standard resumes without machine-readable text, enter the candidate profile manually:
            </p>
            <div className="space-y-3 text-xs">
              <label className="block">
                <span className="font-medium text-slate-700">Candidate Full Name</span>
                <input
                  type="text"
                  placeholder="e.g. Alex Taylor"
                  className="mt-1 block w-full border border-slate-300 rounded p-2 text-xs"
                />
              </label>
              <label className="block">
                <span className="font-medium text-slate-700">Project Name</span>
                <input
                  type="text"
                  placeholder="e.g. Distributed KV Store"
                  className="mt-1 block w-full border border-slate-300 rounded p-2 text-xs"
                />
              </label>
              <label className="block">
                <span className="font-medium text-slate-700">Public GitHub URL</span>
                <input
                  type="url"
                  placeholder="https://github.com/alex/kv-store"
                  className="mt-1 block w-full border border-slate-300 rounded p-2 text-xs"
                />
              </label>
            </div>
            <div className="mt-5 flex items-center justify-end gap-3">
              <button
                type="button"
                onClick={() => setShowManualModal(false)}
                className="px-3 py-1.5 border border-slate-300 rounded text-xs text-slate-700 hover:bg-slate-50"
              >
                Close
              </button>
              <button
                type="button"
                onClick={() => {
                  alert("Manual entry pathway recorded.");
                  setShowManualModal(false);
                }}
                className="px-3 py-1.5 bg-blue-600 text-white rounded text-xs font-semibold hover:bg-blue-700"
              >
                Save Candidate
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
