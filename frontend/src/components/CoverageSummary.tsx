"use client";

import React from "react";

export interface CoverageComponentData {
  score?: number | null;
  weight?: number;
  weightedScore?: number;
  weighted_score?: number;
  status?: string;
  reason?: string | null;
}

interface CoverageSummaryProps {
  score?: number | null;
  status?: string | null;
  components?: Record<string, CoverageComponentData>;
}

export function CoverageSummary({
  score,
  status = "reviewable",
  components = {},
}: CoverageSummaryProps) {
  const componentLabels: Record<string, { label: string; desc: string }> = {
    history_availability: {
      label: "History Availability",
      desc: "Depth and traversal completeness of Git commit logs",
    },
    source_inspection: {
      label: "Source Inspection",
      desc: "Availability of parseable source code files in repository",
    },
    metadata_availability: {
      label: "Metadata Availability",
      desc: "Upstream GitHub repository metadata (license, fork, branch)",
    },
    reference_comparison: {
      label: "Reference Comparison",
      desc: "Syntactic fingerprint overlap against curated benchmark catalog",
    },
  };

  const scoreDisplay = score !== undefined && score !== null ? `${score} / 100` : "Unavailable";

  return (
    <div className="bg-white rounded-lg border border-slate-200 shadow-sm p-6 mb-6" data-testid="coverage-summary">
      {/* Prominent Required Disclaimer */}
      <div
        role="note"
        className="mb-6 p-4 bg-slate-900 text-white rounded-md text-sm font-medium tracking-wide flex items-center justify-between"
        data-testid="evidence-signal-disclaimer"
      >
        <span>
          ⚠️ <strong>Mandatory Notice:</strong> These findings are signals for human review, not proof of authorship or misconduct.
        </span>
      </div>

      <div className="flex flex-col md:flex-row md:items-start justify-between gap-6 border-b border-slate-100 pb-6 mb-6">
        <div>
          <span className="text-xs font-semibold uppercase tracking-wider text-slate-500 block">
            Metric
          </span>
          <h2 className="text-2xl font-bold text-slate-900 mt-0.5">
            Evidence coverage: <span className="text-blue-600">{scoreDisplay}</span>
          </h2>
          <p className="text-xs text-slate-500 mt-1 max-w-xl leading-relaxed">
            Measures data completeness and inspectability across Git history, source files, metadata, and reference comparison.
            This metric <strong>never</strong> represents candidate competence, technical skill, or hiring suitability.
          </p>
        </div>

        <div className="text-left md:text-right">
          <span className="text-xs font-semibold uppercase tracking-wider text-slate-500 block">
            Review Status
          </span>
          <span
            className="inline-block mt-1 text-xs uppercase font-bold tracking-wider px-3 py-1 rounded-full bg-slate-100 text-slate-800 border border-slate-200"
            data-testid="assessment-status"
          >
            {status || "reviewable"}
          </span>
        </div>
      </div>

      {/* Component Breakdown Table */}
      <div>
        <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-600 mb-3">
          Coverage Components Breakdown
        </h3>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs border border-slate-200 rounded-md overflow-hidden">
            <thead className="bg-slate-50 text-slate-700 font-semibold border-b border-slate-200">
              <tr>
                <th scope="col" className="p-3">Component</th>
                <th scope="col" className="p-3">Status</th>
                <th scope="col" className="p-3">Score & Weight</th>
                <th scope="col" className="p-3">Explanation / Reason</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 text-slate-600">
              {Object.keys(components).length === 0 ? (
                <tr>
                  <td colSpan={4} className="p-4 text-center text-slate-400">
                    No individual coverage breakdown available.
                  </td>
                </tr>
              ) : (
                Object.entries(components).map(([key, comp]) => {
                  const meta = componentLabels[key] || {
                    label: key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
                    desc: "Measured evidence factor",
                  };
                  const compStatus = comp.status || "unavailable";
                  const isUnavailable = compStatus === "unavailable" || comp.score === null || comp.score === undefined;

                  return (
                    <tr key={key} className="hover:bg-slate-50/60">
                      <td className="p-3 font-medium text-slate-900">
                        <div>{meta.label}</div>
                        <div className="text-[11px] text-slate-400 font-normal">{meta.desc}</div>
                      </td>
                      <td className="p-3">
                        <span
                          className={`px-2 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wider ${
                            compStatus === "complete"
                              ? "bg-slate-100 text-slate-800 border border-slate-200"
                              : compStatus === "partial"
                              ? "bg-amber-100 text-amber-800 border border-amber-200"
                              : "bg-slate-200 text-slate-700"
                          }`}
                        >
                          {compStatus}
                        </span>
                      </td>
                      <td className="p-3 font-mono">
                        {isUnavailable ? (
                          <span className="text-slate-400">Unavailable</span>
                        ) : (
                          <span>
                            {comp.score}% ({Math.round((comp.weight || 0) * 100)}% wt)
                          </span>
                        )}
                      </td>
                      <td className="p-3 max-w-xs text-slate-500">
                        {comp.reason ? (
                          <span className="text-amber-800">{comp.reason}</span>
                        ) : isUnavailable ? (
                          <span className="text-slate-400">Data unavailable from repository inspect phase.</span>
                        ) : (
                          <span className="text-slate-600">Inspectable data verified.</span>
                        )}
                      </td>
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
