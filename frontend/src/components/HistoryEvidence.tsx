"use client";

import React from "react";

export interface ContributorData {
  name?: string;
  email?: string;
  commit_count?: number;
  commitCount?: number;
  percentage?: number;
}

export interface HistoryEvidenceProps {
  repositoryUrl?: string;
  analyzedSha?: string;
  analysisTime?: string;
  isFork?: boolean;
  parentUrl?: string | null;
  historyCompleteness?: {
    totalCommits?: number;
    total_commits?: number;
    isShallow?: boolean;
    is_shallow?: boolean;
    isTruncated?: boolean;
    is_truncated?: boolean;
    earliestDate?: string | null;
    earliest_commit_date?: string | null;
    latestDate?: string | null;
    latest_commit_date?: string | null;
  };
  contributors?: ContributorData[];
  botCommitCount?: number;
  mergeCommitCount?: number;
}

export function HistoryEvidence({
  repositoryUrl,
  analyzedSha,
  analysisTime,
  isFork,
  parentUrl,
  historyCompleteness,
  contributors = [],
  botCommitCount = 0,
  mergeCommitCount = 0,
}: HistoryEvidenceProps) {
  const totalCommits =
    historyCompleteness?.totalCommits ?? historyCompleteness?.total_commits ?? 0;
  const isShallow =
    historyCompleteness?.isShallow ?? historyCompleteness?.is_shallow ?? false;
  const isTruncated =
    historyCompleteness?.isTruncated ?? historyCompleteness?.is_truncated ?? false;
  const earliestDate =
    historyCompleteness?.earliestDate ?? historyCompleteness?.earliest_commit_date;
  const latestDate =
    historyCompleteness?.latestDate ?? historyCompleteness?.latest_commit_date;

  return (
    <div className="bg-white rounded-lg border border-slate-200 shadow-sm p-6 mb-6" data-testid="history-evidence">
      <div className="border-b border-slate-100 pb-4 mb-5">
        <h3 className="text-base font-semibold text-slate-800">
          Git Repository & Commit History Evidence
        </h3>
        <p className="text-xs text-slate-500 mt-0.5">
          Verified repository attributes and inspectable commit metadata extracted from public Git objects.
        </p>
      </div>

      {/* Distinction of Metadata vs Identity */}
      <div className="bg-slate-50 border border-slate-200 rounded p-3 mb-5 text-xs text-slate-600">
        <strong className="text-slate-800">Data Category Notice:</strong> Commit authors, timestamps, and emails are
        <em> self-declared metadata</em> configured in Git clients and do NOT constitute verified identity proofs or verified authorship.
      </div>

      {/* Key Metrics Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6 text-xs">
        <div className="p-3 bg-slate-50 rounded border border-slate-200">
          <span className="text-slate-500 block mb-0.5">Reachable Commits</span>
          <span className="text-base font-bold text-slate-900 font-mono">
            {totalCommits}
          </span>
          <div className="text-[11px] text-slate-400 mt-1">
            {isShallow ? "Shallow history" : isTruncated ? "Truncated traversal" : "Full reachable log"}
          </div>
        </div>

        <div className="p-3 bg-slate-50 rounded border border-slate-200">
          <span className="text-slate-500 block mb-0.5">Commit Date Span</span>
          <span className="text-xs font-semibold text-slate-800 block truncate font-mono">
            {earliestDate ? new Date(earliestDate).toLocaleDateString() : "Unavailable"} →{" "}
            {latestDate ? new Date(latestDate).toLocaleDateString() : "Unavailable"}
          </span>
          <div className="text-[11px] text-slate-400 mt-1">Active timeline range</div>
        </div>

        <div className="p-3 bg-slate-50 rounded border border-slate-200">
          <span className="text-slate-500 block mb-0.5">Fork Status</span>
          <span className="text-sm font-semibold text-slate-800 block">
            {isFork ? "Forked Repository" : "Root Repository"}
          </span>
          <div className="text-[11px] text-slate-400 mt-1 truncate">
            {parentUrl ? (
              <a href={parentUrl} target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline">
                Upstream: {parentUrl}
              </a>
            ) : (
              "No parent upstream detected"
            )}
          </div>
        </div>

        <div className="p-3 bg-slate-50 rounded border border-slate-200">
          <span className="text-slate-500 block mb-0.5">Special Commits</span>
          <span className="text-xs font-medium text-slate-800 block font-mono">
            Merges: {mergeCommitCount} • Bots: {botCommitCount}
          </span>
          <div className="text-[11px] text-slate-400 mt-1">Automated or merge operations</div>
        </div>
      </div>

      {/* Target Repository & Analyzed SHA */}
      <div className="mb-6 p-3 bg-slate-50 border border-slate-200 rounded text-xs space-y-1 font-mono">
        <div>
          <span className="text-slate-500">Repository URL: </span>
          {repositoryUrl ? (
            <a href={repositoryUrl} target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline">
              {repositoryUrl}
            </a>
          ) : (
            <span className="text-slate-400">Unavailable</span>
          )}
        </div>
        <div>
          <span className="text-slate-500">Analyzed Commit SHA: </span>
          <span className="text-slate-800 font-bold">{analyzedSha || "HEAD (Unavailable)"}</span>
        </div>
        {analysisTime && (
          <div>
            <span className="text-slate-500">Analysis Time: </span>
            <span className="text-slate-700">{new Date(analysisTime).toLocaleString()}</span>
          </div>
        )}
      </div>

      {/* Contributor Distribution Table */}
      <div>
        <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-600 mb-2">
          Self-Declared Contributor Distribution ({contributors.length})
        </h4>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs border border-slate-200 rounded overflow-hidden">
            <thead className="bg-slate-50 text-slate-700 font-semibold border-b border-slate-200">
              <tr>
                <th scope="col" className="p-2.5">Author Name</th>
                <th scope="col" className="p-2.5">Email (Redacted/Anonymized)</th>
                <th scope="col" className="p-2.5">Commits</th>
                <th scope="col" className="p-2.5">Share</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 text-slate-600 font-mono">
              {contributors.length === 0 ? (
                <tr>
                  <td colSpan={4} className="p-3 text-center text-slate-400">
                    No contributor entries parsed from Git logs.
                  </td>
                </tr>
              ) : (
                contributors.map((c, i) => {
                  const count = c.commitCount ?? c.commit_count ?? 0;
                  const pct = c.percentage ?? (totalCommits > 0 ? Math.round((count / totalCommits) * 100) : 0);

                  return (
                    <tr key={i} className="hover:bg-slate-50">
                      <td className="p-2.5 font-medium text-slate-900 font-sans">{c.name || "Unknown Author"}</td>
                      <td className="p-2.5 text-slate-500">{c.email || "redacted"}</td>
                      <td className="p-2.5">{count}</td>
                      <td className="p-2.5 font-semibold text-slate-800">{pct}%</td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
