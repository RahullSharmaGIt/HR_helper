"use client";

import React from "react";

export interface EvidenceItemData {
  id: string;
  kind?: string;
  summary: string;
  source_url?: string | null;
  sourceUrl?: string | null;
  commit_sha?: string | null;
  commitSha?: string | null;
  path?: string | null;
}

interface EvidenceListProps {
  evidence: EvidenceItemData[];
}

export function EvidenceList({ evidence = [] }: EvidenceListProps) {
  const getKindBadgeClass = (kind?: string) => {
    switch (kind) {
      case "git_history":
        return "bg-slate-100 text-slate-800 border-slate-300";
      case "similarity":
        return "bg-blue-100 text-blue-800 border-blue-200";
      case "metadata":
        return "bg-purple-100 text-purple-800 border-purple-200";
      default:
        return "bg-slate-100 text-slate-700 border-slate-200";
    }
  };

  const getEvidenceCategory = (kind?: string) => {
    switch (kind) {
      case "git_history":
        return "Author metadata (Git commit headers)";
      case "similarity":
        return "Syntactic similarity observation";
      case "metadata":
        return "Verified repository metadata";
      default:
        return "System observation";
    }
  };

  return (
    <div className="bg-white rounded-lg border border-slate-200 shadow-sm p-6 mb-6" data-testid="evidence-list-panel">
      <div className="border-b border-slate-100 pb-4 mb-5">
        <h3 className="text-base font-semibold text-slate-800">
          Supporting Evidence Items Catalog ({evidence.length})
        </h3>
        <p className="text-xs text-slate-500 mt-0.5">
          Atomic evidence records supporting assessment observations and interview suggestions.
        </p>
      </div>

      {evidence.length === 0 ? (
        <div className="p-4 bg-slate-50 border border-slate-200 rounded text-center text-xs text-slate-500">
          No atomic evidence items cataloged for this report.
        </div>
      ) : (
        <ul className="space-y-4">
          {evidence.map((item) => {
            const sourceUrl = item.sourceUrl || item.source_url;
            const commitSha = item.commitSha || item.commit_sha;
            const filePath = item.path;

            return (
              <li
                key={item.id}
                id={`evidence-${item.id}`}
                className="p-4 rounded-md border border-slate-200 bg-slate-50/40 hover:border-slate-300 transition-colors"
                data-testid={`evidence-item-${item.id}`}
              >
                <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
                  <div className="flex items-center gap-2">
                    <span className="text-[11px] font-mono px-2 py-0.5 rounded bg-white border border-slate-200 text-slate-700 font-bold">
                      #{item.id.substring(0, 8)}
                    </span>
                    <span
                      className={`text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded border ${getKindBadgeClass(
                        item.kind
                      )}`}
                    >
                      {item.kind || "observation"}
                    </span>
                  </div>

                  <span className="text-[11px] text-slate-500 italic">
                    {getEvidenceCategory(item.kind)}
                  </span>
                </div>

                <p className="text-xs text-slate-800 font-medium leading-relaxed mb-2">
                  {item.summary}
                </p>

                {/* Source links & Details */}
                <div className="text-[11px] text-slate-500 space-y-1 font-mono pt-2 border-t border-slate-200/60">
                  {sourceUrl && (
                    <div className="break-all">
                      <span className="text-slate-400">Source: </span>
                      <a
                        href={sourceUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-blue-600 hover:underline"
                      >
                        {sourceUrl}
                      </a>
                    </div>
                  )}

                  {commitSha && (
                    <div className="break-all">
                      <span className="text-slate-400">Commit SHA: </span>
                      <span className="text-slate-700">{commitSha}</span>
                    </div>
                  )}

                  {filePath && (
                    <div className="break-all">
                      <span className="text-slate-400">File Path: </span>
                      <span className="text-slate-700">{filePath}</span>
                    </div>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
