"use client";

import React from "react";

export interface SimilarityMatchData {
  candidate_path?: string;
  candidatePath?: string;
  reference_repo_url?: string;
  referenceRepoUrl?: string;
  reference_commit_sha?: string;
  referenceCommitSha?: string;
  similarity_ratio?: number;
  similarityRatio?: number;
  benchmark_project_name?: string;
  benchmarkProjectName?: string;
  benchmark_category?: string;
  benchmarkCategory?: string;
}

export interface SimilarityEvidenceProps {
  overallRatio?: number | null;
  matches?: SimilarityMatchData[];
  coverageStatistics?: Record<string, unknown>;
  algorithmVersion?: string;
  limitations?: string[];
  candidateRepoUrl?: string;
  comparisonStatus?: string;
}

export function SimilarityEvidence({
  overallRatio = 0,
  matches = [],
  coverageStatistics = {},
  algorithmVersion = "1.0.0",
  limitations = [],
  candidateRepoUrl,
  comparisonStatus,
}: SimilarityEvidenceProps) {
  const displayRatio =
    overallRatio !== null && overallRatio !== undefined
      ? `${Math.round(overallRatio * 100)}%`
      : "Unavailable";

  const statusText =
    comparisonStatus
      ? comparisonStatus.charAt(0).toUpperCase() + comparisonStatus.slice(1)
      : overallRatio !== null && overallRatio !== undefined
      ? "Complete"
      : "Unavailable";

  let riskBadge = { text: "Undetermined", bg: "bg-slate-100 text-slate-700 border-slate-300" };
  if (overallRatio !== null && overallRatio !== undefined) {
    if (overallRatio >= 0.7) {
      riskBadge = { text: "High Similarity Risk", bg: "bg-red-50 text-red-700 border-red-200" };
    } else if (overallRatio >= 0.35) {
      riskBadge = { text: "Moderate Overlap", bg: "bg-amber-50 text-amber-700 border-amber-200" };
    } else {
      riskBadge = { text: "Low Syntactic Overlap", bg: "bg-emerald-50 text-emerald-700 border-emerald-200" };
    }
  }

  // Find unique benchmark projects matched
  const matchedProjects = Array.from(
    new Set(
      matches
        .map((m) => m.benchmarkProjectName || m.benchmark_project_name)
        .filter(Boolean) as string[]
    )
  );

  return (
    <div className="bg-white rounded-lg border border-slate-200 shadow-sm p-6 mb-6" data-testid="similarity-evidence">
      <div className="border-b border-slate-100 pb-4 mb-5">
        <h3 className="text-base font-semibold text-slate-800">
          Curated Reference Similarity Analysis
        </h3>
        <p className="text-xs text-slate-500 mt-0.5">
          Deterministic winnowing fingerprint comparison against configured reference repositories.
        </p>
      </div>

      {/* Reference Boundaries & Limits */}
      <div className="bg-slate-50 border border-slate-200 rounded p-3 mb-5 text-xs text-slate-600 space-y-1">
        <div className="font-semibold text-slate-800">Reference Collection Scope & Boundary:</div>
        <p>
          Similarity compares candidate source tokens against a <em>small, pinned reference collection only</em>.
          It is NOT an exhaustive index of all public code, tutorials, or open source repositories.
          Similarity reflects shared syntactic structure and does NOT imply copying direction, plagiarism, or intellectual property violation.
        </p>
      </div>

      {/* Ratio & Stats Summary */}
      <div className="grid grid-cols-1 sm:grid-cols-4 gap-4 mb-6 text-xs">
        <div className="p-3 bg-slate-50 rounded border border-slate-200">
          <span className="text-slate-500 block mb-0.5">Reference Comparison</span>
          <span className="text-base font-bold text-slate-900 font-mono">
            {statusText}
          </span>
          <div className="text-[11px] text-slate-400 mt-0.5">Catalog status (25% weight)</div>
        </div>

        <div className="p-3 bg-slate-50 rounded border border-slate-200">
          <span className="text-slate-500 block mb-0.5">Overall Similarity Score</span>
          <span className="text-base font-bold text-slate-900 font-mono" data-testid="overall-similarity-ratio">
            {displayRatio}
          </span>
          <div className="text-[11px] text-slate-400 mt-0.5">Syntactic shingle alignment</div>
        </div>

        <div className="p-3 bg-slate-50 rounded border border-slate-200">
          <span className="text-slate-500 block mb-0.5">Syntactic Risk Level</span>
          <span className={`inline-block px-2 py-0.5 rounded text-xs font-semibold border ${riskBadge.bg} mt-0.5`}>
            {riskBadge.text}
          </span>
          <div className="text-[11px] text-slate-400 mt-1">Benchmark alignment</div>
        </div>

        <div className="p-3 bg-slate-50 rounded border border-slate-200">
          <span className="text-slate-500 block mb-0.5">Matched Benchmark Project</span>
          <span className="text-xs font-semibold text-slate-900 truncate block">
            {matchedProjects.length > 0 ? matchedProjects.join(", ") : "None detected"}
          </span>
          <div className="text-[11px] text-slate-400 mt-0.5">5 Initial categories</div>
        </div>
      </div>

      {candidateRepoUrl && (
        <div className="p-3 bg-slate-50 rounded border border-slate-200 text-xs text-slate-600 mb-6 flex flex-wrap items-center justify-between gap-2">
          <div>
            <span className="font-semibold text-slate-700">Candidate Repository:</span>{" "}
            <a
              href={candidateRepoUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="text-blue-600 hover:underline font-mono"
            >
              {candidateRepoUrl}
            </a>
          </div>
          <div className="text-[11px] text-slate-500">
            Algorithm: <span className="font-mono">Winnowing v{algorithmVersion}</span>
          </div>
        </div>
      )}

      {/* Matches Table */}
      <div className="mb-6">
        <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-600 mb-2">
          Matched Files & Benchmark Repositories ({matches.length})
        </h4>

        {matches.length === 0 ? (
          <div className="p-4 bg-slate-50 border border-slate-200 rounded text-center text-xs text-slate-500">
            No significant code similarity detected against the configured reference collection.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs border border-slate-200 rounded overflow-hidden">
              <thead className="bg-slate-50 text-slate-700 font-semibold border-b border-slate-200">
                <tr>
                  <th scope="col" className="p-2.5">Candidate File Path</th>
                  <th scope="col" className="p-2.5">Benchmark Project</th>
                  <th scope="col" className="p-2.5">Original Benchmark Repository</th>
                  <th scope="col" className="p-2.5">Pinned Commit SHA</th>
                  <th scope="col" className="p-2.5">Overlap</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 text-slate-600">
                {matches.map((m, idx) => {
                  const path = m.candidatePath || m.candidate_path || "unknown";
                  const repoUrl = m.referenceRepoUrl || m.reference_repo_url || "";
                  const commitSha = m.referenceCommitSha || m.reference_commit_sha || "";
                  const ratio = m.similarityRatio ?? m.similarity_ratio ?? 0;
                  const projName = m.benchmarkProjectName || m.benchmark_project_name || "Benchmark Project";
                  const category = m.benchmarkCategory || m.benchmark_category;

                  return (
                    <tr key={idx} className="hover:bg-slate-50">
                      <td className="p-2.5 font-mono text-slate-900 break-all max-w-xs">
                        {path}
                      </td>
                      <td className="p-2.5">
                        <div className="font-semibold text-slate-800">{projName}</div>
                        {category && <div className="text-[11px] text-slate-400">{category}</div>}
                      </td>
                      <td className="p-2.5 max-w-sm">
                        {repoUrl ? (
                          <a
                            href={repoUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-blue-600 hover:underline font-mono break-all"
                          >
                            {repoUrl}
                          </a>
                        ) : (
                          <span className="text-slate-400 font-mono">Unknown benchmark</span>
                        )}
                      </td>
                      <td className="p-2.5 font-mono text-[11px] text-slate-500">
                        {commitSha ? (
                          <span title={commitSha}>{commitSha.substring(0, 8)}...</span>
                        ) : (
                          "Pinned SHA N/A"
                        )}
                      </td>
                      <td className="p-2.5 font-mono font-semibold text-slate-800">
                        {Math.round(ratio * 100)}%
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Limitations Notes */}
      {limitations.length > 0 && (
        <div className="p-3 bg-slate-50 rounded border border-slate-200 text-xs text-slate-500 space-y-1">
          <span className="font-semibold text-slate-700 block">Similarity Limitations:</span>
          <ul className="list-disc list-inside space-y-0.5 text-[11px]">
            {limitations.map((lim, i) => (
              <li key={i}>{lim}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
