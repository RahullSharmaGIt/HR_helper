"use client";

import React, { useCallback, useEffect, useState, use } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ProjectSelector } from "@/components/ProjectSelector";
import { RepositorySelector } from "@/components/RepositorySelector";
import { JobStatus } from "@/components/JobStatus";
import {
  getCandidate,
  selectCandidateProject,
  listProjectRepositories,
  discoverProjectRepositories,
  confirmRepositorySelection,
  triggerProjectAnalysis,
  deleteCandidate,
  type CandidateDetailResponse,
  type RepositorySelectionResponse,
} from "@/lib/api";

interface CandidatePageProps {
  params: Promise<{ id: string }>;
}

export default function CandidateDetailPage({ params }: CandidatePageProps) {
  const router = useRouter();
  const { id: candidateId } = use(params);

  const [candidate, setCandidate] = useState<CandidateDetailResponse | null>(null);
  const [repositories, setRepositories] = useState<RepositorySelectionResponse[]>([]);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [reposLoading, setReposLoading] = useState<boolean>(false);
  const [generalError, setGeneralError] = useState<string | null>(null);
  const [showDeleteModal, setShowDeleteModal] = useState<boolean>(false);
  const [isDeleting, setIsDeleting] = useState<boolean>(false);
  const [dismissJobAlert, setDismissJobAlert] = useState<boolean>(false);

  const loadCandidate = useCallback(async () => {
    setLoading(true);
    setGeneralError(null);
    try {
      const data = await getCandidate(candidateId);
      setCandidate(data);

      if (data.selectedProjectId) {
        setReposLoading(true);
        const repos = await listProjectRepositories(data.selectedProjectId);
        setRepositories(repos);
        setReposLoading(false);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to load candidate.";
      setGeneralError(msg);
    } finally {
      setLoading(false);
    }
  }, [candidateId]);

  useEffect(() => {
    loadCandidate();
  }, [loadCandidate]);

  const handleSelectProject = async (projectId: string) => {
    try {
      const updated = await selectCandidateProject(candidateId, projectId);
      setCandidate(updated);
      setReposLoading(true);
      const repos = await listProjectRepositories(projectId);
      setRepositories(repos);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to select project.";
      setGeneralError(msg);
    } finally {
      setReposLoading(false);
    }
  };

  const handleRefreshRepositories = async (limit: number = 10) => {
    if (!candidate?.selectedProjectId) return;
    setReposLoading(true);
    setGeneralError(null);
    try {
      const repos = await discoverProjectRepositories(candidate.selectedProjectId, limit);
      setRepositories(repos);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to refresh repositories.";
      setGeneralError(msg);
    } finally {
      setReposLoading(false);
    }
  };

  const handleConfirmRepository = async (selectionId: string) => {
    if (!candidate?.selectedProjectId) return;
    try {
      await confirmRepositorySelection(candidate.selectedProjectId, {
        repositorySelectionId: selectionId,
      });
      // Refresh repository list to reflect confirmation
      const repos = await listProjectRepositories(candidate.selectedProjectId);
      setRepositories(repos);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to confirm repository.";
      setGeneralError(msg);
      throw err;
    }
  };

  const handleTriggerAnalysis = async () => {
    if (!candidate?.selectedProjectId) return;
    try {
      const job = await triggerProjectAnalysis(candidate.selectedProjectId);
      setActiveJobId(job.id);
      setDismissJobAlert(false);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to trigger analysis.";
      setGeneralError(msg);
      throw err;
    }
  };

  const handleDeleteCandidate = async () => {
    setIsDeleting(true);
    try {
      await deleteCandidate(candidateId);
      router.push("/");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to delete candidate.";
      setGeneralError(msg);
      setIsDeleting(false);
      setShowDeleteModal(false);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center p-8 text-sm text-slate-500">
        <svg className="animate-spin h-5 w-5 mr-3 text-slate-900" fill="none" viewBox="0 0 24 24">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
        </svg>
        Loading candidate review studio...
      </div>
    );
  }

  if (!candidate) {
    return (
      <div className="min-h-screen bg-slate-50 flex flex-col items-center justify-center p-8">
        <p className="text-slate-800 text-sm mb-4 font-medium">Candidate not found or deleted.</p>
        <Link href="/" className="text-slate-900 underline text-xs font-semibold hover:text-slate-700">
          Return to All Candidates
        </Link>
      </div>
    );
  }

  const confirmedRepo = repositories.find((r) => r.isConfirmed);
  const firstResume = candidate.resumes && candidate.resumes.length > 0 ? candidate.resumes[0] : null;

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 antialiased flex flex-col justify-between">
      {/* Top Navigation Header */}
      <header className="sticky top-0 z-30 bg-white border-b border-slate-200 shadow-xs" data-purpose="primary-navbar">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <div className="flex items-center space-x-3 sm:space-x-4">
            <Link
              href="/"
              className="inline-flex items-center text-sm font-medium text-slate-500 hover:text-slate-900 transition-colors group"
            >
              <svg
                className="w-4 h-4 mr-1.5 text-slate-400 group-hover:-translate-x-0.5 transition-transform"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path d="M10 19l-7-7m0 0l7-7m-7 7h18" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" />
              </svg>
              All Candidates
            </Link>
            <span className="text-slate-300">/</span>
            <span className="text-xs uppercase tracking-wider font-semibold px-2 py-0.5 rounded bg-slate-100 text-slate-600 border border-slate-200 font-mono">
              ID: {candidate.id.slice(0, 8).toUpperCase()}
            </span>
          </div>

          {/* Right Status Badges & Delete Action */}
          <div className="flex items-center space-x-2.5 sm:space-x-3">
            <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-amber-50 text-amber-800 border border-amber-200/80">
              <span className="w-1.5 h-1.5 rounded-full bg-amber-500 mr-1.5 animate-pulse" />
              Evidence-only verification
            </span>
            <span className="hidden md:inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-slate-100 text-slate-600 border border-slate-200">
              No automated scoring
            </span>
            <button
              type="button"
              onClick={() => setShowDeleteModal(true)}
              className="text-xs font-medium text-red-600 hover:text-red-700 hover:bg-red-50 px-2.5 py-1.5 rounded-lg border border-red-200 transition-colors"
              data-testid="delete-candidate-button"
            >
              Delete Candidate
            </button>
          </div>
        </div>
      </header>

      {/* Main Container */}
      <main className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-8 w-full flex-1" data-purpose="candidate-review-workflow">
        {generalError && (
          <div
            role="alert"
            className="mb-6 p-4 bg-red-50 border border-red-200 rounded-xl text-sm text-red-800 flex items-center justify-between"
          >
            <span>{generalError}</span>
            <button
              onClick={() => setGeneralError(null)}
              className="text-xs text-red-700 font-bold hover:underline ml-4"
            >
              Dismiss
            </button>
          </div>
        )}

        {/* Candidate Overview Card */}
        <div className="bg-white rounded-xl border border-slate-200 shadow-xs p-6 mb-6">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div>
              <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-slate-900">
                Candidate Review: {candidate.name}
              </h1>
              <div className="mt-2 flex flex-wrap items-center gap-y-2 gap-x-6 text-sm text-slate-600">
                <div className="flex items-center gap-1.5">
                  <svg className="w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path
                      d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth="2"
                    />
                  </svg>
                  <span>
                    Email: <strong className="font-medium text-slate-800">{candidate.email || "Not specified"}</strong>
                  </span>
                </div>
                <div className="flex items-center gap-1.5">
                  <svg className="w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path
                      d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth="2"
                    />
                  </svg>
                  <span>
                    Uploaded: <span className="font-mono text-slate-800">{new Date(candidate.createdAt).toLocaleDateString()}</span>
                  </span>
                </div>
                <div className="flex items-center gap-1.5">
                  <svg className="w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path
                      d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth="2"
                    />
                  </svg>
                  <span>
                    Source Files: <strong className="font-medium text-slate-800">{(candidate.resumes || []).length}</strong>
                  </span>
                </div>
              </div>
            </div>

            <div className="flex items-center gap-2">
              {firstResume ? (
                <a
                  href={`/api/v1/resumes/${firstResume.id}/download`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="px-3.5 py-1.5 text-xs font-semibold uppercase tracking-wider rounded-lg border border-slate-300 text-slate-700 bg-white hover:bg-slate-50 transition-colors shadow-xs inline-flex items-center gap-1.5"
                >
                  <svg className="w-3.5 h-3.5 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path
                      d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth="2"
                    />
                  </svg>
                  <span>View Source PDF</span>
                </a>
              ) : (
                <span className="text-xs text-slate-400 italic">No source resume file</span>
              )}
            </div>
          </div>
        </div>

        {/* Active Job Alert Banner */}
        {activeJobId && !dismissJobAlert && (
          <section className="mb-8" data-purpose="active-job-alert">
            <div className="bg-blue-50/70 border border-blue-200 rounded-xl p-4 flex items-start justify-between gap-3 text-sm text-blue-900 shadow-xs">
              <div className="flex items-start gap-3">
                <svg className="w-5 h-5 text-blue-600 mt-0.5 flex-shrink-0 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path
                    className="opacity-75"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                    fill="currentColor"
                  />
                </svg>
                <div className="text-xs sm:text-sm leading-relaxed">
                  <span className="font-semibold text-blue-950">Active Background Analysis:</span>{" "}
                  Job <code className="font-mono bg-blue-100 text-blue-800 px-1 py-0.5 rounded text-xs">{activeJobId}</code>{" "}
                  is executing across repository Git history and evidence reference catalog.
                </div>
              </div>
              <button
                type="button"
                onClick={() => setDismissJobAlert(true)}
                className="text-xs font-medium text-blue-700 hover:text-blue-900 hover:bg-blue-100 px-2 py-1 rounded transition-colors whitespace-nowrap"
              >
                Dismiss
              </button>
            </div>
          </section>
        )}

        {/* Step 1: Project Selection */}
        <ProjectSelector
          candidateId={candidate.id}
          projects={candidate.projects || []}
          selectedProjectId={candidate.selectedProjectId || null}
          onSelectProject={handleSelectProject}
        />

        {/* Step 2: Repository Confirmation Gate */}
        {candidate.selectedProjectId ? (
          <RepositorySelector
            projectId={candidate.selectedProjectId}
            repositories={repositories}
            onConfirmRepository={handleConfirmRepository}
            onTriggerAnalysis={handleTriggerAnalysis}
            hasActiveJob={Boolean(activeJobId)}
            loading={reposLoading}
            onRefreshRepositories={handleRefreshRepositories}
          />
        ) : (
          <div className="p-8 bg-white border border-dashed border-slate-300 rounded-xl text-center text-xs text-slate-500 mb-10">
            Please select a candidate project above to discover and confirm candidate GitHub repositories.
          </div>
        )}

        {/* Step 3: Analysis Job Status */}
        {activeJobId && (
          <JobStatus
            jobId={activeJobId}
            onRetry={handleTriggerAnalysis}
            onJobCanceled={() => {
              setActiveJobId(null);
            }}
          />
        )}
      </main>

      {/* Sticky Bottom Action Bar */}
      <footer className="sticky bottom-0 z-40 bg-white/95 backdrop-blur-md border-t border-slate-200 py-3.5 shadow-lg" data-purpose="execution-bar">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 flex flex-col sm:flex-row items-center justify-between gap-4">
          {/* Stage Progression Hints */}
          <div className="flex items-center text-xs space-x-2 overflow-x-auto w-full sm:w-auto pb-1 sm:pb-0">
            {candidate.selectedProjectId ? (
              <span className="text-emerald-700 font-semibold flex items-center">
                <svg className="w-3.5 h-3.5 mr-1" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                </svg>
                1. Project Selected
              </span>
            ) : (
              <span className="text-slate-400 font-medium">1. Project Selection</span>
            )}

            <span className="text-slate-300">→</span>

            {confirmedRepo ? (
              <span className="text-emerald-700 font-semibold flex items-center">
                <svg className="w-3.5 h-3.5 mr-1" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                </svg>
                2. Repository Confirmed
              </span>
            ) : (
              <span className="text-slate-400 font-medium">2. Repository Confirmation</span>
            )}

            <span className="text-slate-300">→</span>

            <span className={activeJobId ? "text-emerald-700 font-semibold flex items-center" : confirmedRepo ? "font-bold text-slate-900" : "text-slate-400 font-medium"}>
              {activeJobId ? "3. Analysis Running" : "3. Trigger Analysis"}
            </span>
          </div>

          {/* Action Button Group */}
          <div className="flex items-center gap-3 w-full sm:w-auto justify-end">
            {confirmedRepo && (
              <div className="text-right hidden sm:block">
                <p className="text-xs font-semibold text-slate-900">Repository confirmed for analysis</p>
                <p className="text-[11px] text-slate-500 font-mono">{confirmedRepo.owner}/{confirmedRepo.name}</p>
              </div>
            )}
            <button
              type="button"
              onClick={handleTriggerAnalysis}
              disabled={!confirmedRepo || Boolean(activeJobId)}
              className="w-full sm:w-auto inline-flex items-center justify-center gap-2 bg-slate-900 hover:bg-slate-800 active:scale-[0.99] text-white font-medium text-sm px-5 py-2.5 rounded-lg shadow-xs transition-all focus:outline-none focus:ring-2 focus:ring-slate-900 focus:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <span>{activeJobId ? "Analysis In Progress" : "Trigger Evidence Analysis"}</span>
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path d="M14 5l7 7m0 0l-7 7m7-7H3" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" />
              </svg>
            </button>
          </div>
        </div>
      </footer>

      {/* Candidate Deletion Confirmation Dialog */}
      {showDeleteModal && (
        <div
          role="dialog"
          aria-modal="true"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-xs p-4"
          data-testid="delete-confirmation-dialog"
        >
          <div className="bg-white rounded-xl shadow-2xl max-w-md w-full p-6 space-y-4 border border-slate-200">
            <h3 className="text-base font-bold text-slate-900">
              Confirm Permanent Candidate Deletion
            </h3>
            <p className="text-xs text-slate-600 leading-relaxed">
              Deleting candidate <strong>{candidate.name}</strong> is permanent and will remove:
            </p>
            <ul className="text-xs text-slate-600 list-disc list-inside space-y-1 bg-red-50/60 p-3 rounded-lg border border-red-100">
              <li>Candidate database records, metadata, and extracted projects</li>
              <li>Stored resume source documents from disk</li>
              <li>Active and queued background analysis jobs</li>
              <li>All cloned repository Git workspaces and similarity reports</li>
            </ul>
            <div className="flex items-center justify-end gap-3 pt-2">
              <button
                type="button"
                onClick={() => setShowDeleteModal(false)}
                disabled={isDeleting}
                className="px-3.5 py-2 border border-slate-300 rounded-lg text-xs font-semibold text-slate-700 hover:bg-slate-50 transition"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleDeleteCandidate}
                disabled={isDeleting}
                className="px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded-lg text-xs font-semibold shadow-xs disabled:opacity-50 transition"
                data-testid="confirm-delete-button"
              >
                {isDeleting ? "Deleting..." : "Permanently Delete"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
