"use client";

import React, { useState } from "react";
import type { RepositorySelectionResponse } from "@/lib/api";

interface RepositorySelectorProps {
  projectId: string;
  repositories: RepositorySelectionResponse[];
  onConfirmRepository: (selectionId: string) => Promise<void>;
  onTriggerAnalysis: () => Promise<void>;
  hasActiveJob: boolean;
  loading?: boolean;
}

export function RepositorySelector({
  repositories,
  onConfirmRepository,
  onTriggerAnalysis,
  hasActiveJob,
  loading = false,
}: RepositorySelectorProps) {
  const [selectedRepoId, setSelectedRepoId] = useState<string | null>(() => {
    const confirmed = repositories.find((r) => r.isConfirmed);
    return confirmed ? confirmed.id : repositories[0]?.id || null;
  });
  const [isConfirming, setIsConfirming] = useState<boolean>(false);
  const [isTriggering, setIsTriggering] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const confirmedSelection = repositories.find((r) => r.isConfirmed);
  const isSelectedConfirmed = Boolean(
    confirmedSelection && confirmedSelection.id === selectedRepoId
  );

  const handleConfirm = async () => {
    if (!selectedRepoId || isConfirming) return;
    setIsConfirming(true);
    setErrorMessage(null);
    try {
      await onConfirmRepository(selectedRepoId);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to confirm repository.";
      setErrorMessage(msg);
    } finally {
      setIsConfirming(false);
    }
  };

  const handleStartAnalysis = async () => {
    if (!isSelectedConfirmed || isTriggering || hasActiveJob) return;
    setIsTriggering(true);
    setErrorMessage(null);
    try {
      await onTriggerAnalysis();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to enqueue analysis job.";
      setErrorMessage(msg);
    } finally {
      setIsTriggering(false);
    }
  };

  return (
    <section className="mb-10" data-purpose="step-2-github-confirmation-gate">
      {/* Step Header */}
      <div className="pb-3 mb-4 border-b border-slate-200">
        <div className="text-xs uppercase font-bold tracking-wider text-slate-400">Step 2</div>
        <h2 className="text-xl font-bold text-slate-900">
          2. Discovered Public Repositories &amp; Confirmation Gate
        </h2>
        <p className="text-sm text-slate-500 mt-0.5">
          Public GitHub repositories discovered via heuristic queries. Human review and explicit confirmation are required.
        </p>
      </div>

      {/* Discovery Uncertainty & Identity Notice */}
      <div
        className="bg-amber-50/70 border border-amber-300/80 rounded-xl p-4 sm:p-5 mb-6 text-amber-900 shadow-xs"
        data-purpose="heuristic-disclaimer"
        data-testid="discovery-uncertainty-notice"
      >
        <div className="flex items-start gap-3">
          <div className="p-1 rounded-md bg-amber-100 text-amber-700 flex-shrink-0 mt-0.5">
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth="2"
              />
            </svg>
          </div>
          <div>
            <h3 className="text-sm font-bold text-amber-950 flex items-center gap-1.5">
              Heuristic Match &amp; Identity Uncertainty
            </h3>
            <p className="text-xs sm:text-sm text-amber-900 mt-1 leading-relaxed">
              Discovered repositories are heuristic suggestions matched by project keywords. Commits, usernames, and repository ownership do <strong>NOT</strong> prove candidate identity or technical authorship.
            </p>
          </div>
        </div>
      </div>

      {errorMessage && (
        <div
          role="alert"
          className="mb-4 p-4 bg-red-50 border border-red-200 rounded-xl text-xs text-red-800 flex items-center justify-between"
        >
          <span>{errorMessage}</span>
          <button
            onClick={() => setErrorMessage(null)}
            className="text-red-700 font-bold hover:underline"
          >
            Dismiss
          </button>
        </div>
      )}

      {repositories.length === 0 ? (
        <div className="text-center py-8 bg-white border border-dashed border-slate-300 rounded-xl text-xs text-slate-500 mb-6">
          {loading
            ? "Discovering public repositories from candidate resume and metadata..."
            : "No public repository candidates found for this project yet."}
        </div>
      ) : (
        <div
          role="radiogroup"
          aria-label="GitHub Repository Selection"
          className="space-y-3.5 mb-6"
        >
          {repositories.map((repo) => {
            const isSelected = selectedRepoId === repo.id;
            const isConfirmed = repo.isConfirmed;

            return (
              <label
                key={repo.id}
                htmlFor={`repo-radio-${repo.id}`}
                onClick={() => setSelectedRepoId(repo.id)}
                className={`block p-4 sm:p-5 rounded-xl cursor-pointer transition-all ${
                  isSelected
                    ? "border-2 border-slate-900 bg-white ring-1 ring-slate-900/10 shadow-md"
                    : "border border-slate-200 bg-white hover:border-slate-300 shadow-xs"
                }`}
              >
                <div className="flex items-start gap-3.5">
                  <input
                    type="radio"
                    id={`repo-radio-${repo.id}`}
                    name="selected_repo"
                    checked={isSelected}
                    onChange={() => setSelectedRepoId(repo.id)}
                    className="mt-1 h-4 w-4 text-slate-900 border-slate-300 focus:ring-slate-900 cursor-pointer"
                  />
                  <div className="w-full">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-mono text-sm font-bold text-slate-950">
                          {repo.owner}/{repo.name}
                        </span>
                        <span className="text-[10px] font-mono uppercase tracking-wider px-2 py-0.5 rounded bg-slate-100 text-slate-600 border border-slate-200">
                          Confidence: {repo.confidenceCategory}
                        </span>
                        {isConfirmed && (
                          <span className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold bg-slate-900 text-white">
                            <svg className="w-3 h-3 mr-1 text-emerald-400" fill="currentColor" viewBox="0 0 20 20">
                              <path
                                fillRule="evenodd"
                                d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
                                clipRule="evenodd"
                              />
                            </svg>
                            Confirmed Selection
                          </span>
                        )}
                      </div>
                    </div>

                    <div className="mt-1.5 flex items-center gap-1.5 text-xs">
                      <a
                        href={repo.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        onClick={(e) => e.stopPropagation()}
                        className="font-mono text-blue-600 hover:underline inline-flex items-center gap-1"
                      >
                        {repo.url}
                        <svg className="w-3 h-3 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path
                            d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            strokeWidth="2"
                          />
                        </svg>
                      </a>
                    </div>

                    <div className="mt-2 text-xs text-slate-500 flex flex-wrap items-center gap-x-4 gap-y-1">
                      <span>
                        Owner: <strong className="font-semibold text-slate-700">{repo.owner}</strong>
                      </span>
                      <span>•</span>
                      <span>
                        Discovery reason: <em>{repo.discoveryReason}</em>
                      </span>
                    </div>
                  </div>
                </div>
              </label>
            );
          })}
        </div>
      )}

      {/* Confirmation & Analysis Action Gate */}
      <div className="flex flex-wrap items-center justify-between gap-4 pt-4 border-t border-slate-200">
        <div>
          {!isSelectedConfirmed ? (
            <button
              type="button"
              onClick={handleConfirm}
              disabled={!selectedRepoId || isConfirming || loading}
              title="Confirm This Repository"
              className="px-4 py-2 bg-slate-900 hover:bg-slate-800 text-white rounded-lg text-xs font-semibold shadow-xs disabled:opacity-50 disabled:cursor-not-allowed transition"
            >
              {isConfirming ? "Confirming..." : "Confirm Selected Repository"}
            </button>
          ) : (
            <span className="text-xs text-emerald-700 font-semibold flex items-center gap-1.5">
              <svg className="w-4 h-4 text-emerald-600" fill="currentColor" viewBox="0 0 20 20">
                <path
                  fillRule="evenodd"
                  d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z"
                  clipRule="evenodd"
                />
              </svg>
              Repository selection confirmed for analysis.
            </span>
          )}
        </div>

        <div>
          <button
            type="button"
            onClick={handleStartAnalysis}
            disabled={!isSelectedConfirmed || isTriggering || hasActiveJob || loading}
            aria-busy={isTriggering}
            title="Start Repository Analysis"
            className="px-5 py-2.5 bg-slate-900 hover:bg-slate-800 text-white rounded-lg text-xs font-semibold shadow-xs disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2 transition"
          >
            {isTriggering ? (
              <>
                <svg className="animate-spin h-3.5 w-3.5 text-white" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                </svg>
                Enqueueing Job...
              </>
            ) : hasActiveJob ? (
              "Analysis In Progress"
            ) : (
              <>
                <span>Trigger Evidence Analysis</span>
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path d="M14 5l7 7m0 0l-7 7m7-7H3" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" />
                </svg>
              </>
            )}
          </button>
        </div>
      </div>
    </section>
  );
}
