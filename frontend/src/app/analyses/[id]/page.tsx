"use client";

import React, { useEffect, useState, use } from "react";
import Link from "next/link";
import { getAnalysisReport } from "@/lib/api";
import { CoverageSummary, type CoverageComponentData } from "@/components/CoverageSummary";
import { HistoryEvidence, type ContributorData } from "@/components/HistoryEvidence";
import { SimilarityEvidence, type SimilarityMatchData } from "@/components/SimilarityEvidence";
import { EvidenceList, type EvidenceItemData } from "@/components/EvidenceList";

interface AnalysisReportPageProps {
  params: Promise<{ id: string }>;
}

export default function AnalysisReportPage({ params }: AnalysisReportPageProps) {
  const { id: jobId } = use(params);

  const [report, setReport] = useState<Record<string, any> | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function loadReport() {
      setLoading(true);
      setError(null);
      try {
        const data = await getAnalysisReport(jobId);
        setReport(data);
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : "Failed to load evidence report.";
        setError(msg);
      } finally {
        setLoading(false);
      }
    }

    loadReport();
  }, [jobId]);

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center p-8 text-sm text-slate-500">
        Loading evidence analysis report for {jobId}...
      </div>
    );
  }

  if (error || !report) {
    return (
      <div className="min-h-screen bg-slate-50 flex flex-col items-center justify-center p-8">
        <div role="alert" className="p-4 bg-red-50 border border-red-200 rounded text-sm text-red-800 mb-4 max-w-md text-center">
          {error || "Report not found."}
        </div>
        <Link href="/" className="text-xs font-semibold text-blue-600 underline">
          Return to Dashboard
        </Link>
      </div>
    );
  }

  // Safe extractions supporting both snake_case and camelCase serialization
  const repoMeta = report.repository || {};
  const historyData = report.history || {};
  const similarityData = report.similarity || {};
  const assessmentData = report.assessment || {};
  const evidenceItems: EvidenceItemData[] = report.evidence || [];
  const limitationsList: string[] = report.limitations || assessmentData.limitations || [];

  const coverageScore: number | null | undefined =
    assessmentData.evidenceCoverageScore ?? assessmentData.evidence_coverage_score;
  const assessmentStatus: string = assessmentData.status || "reviewable";
  const coverageComponents: Record<string, CoverageComponentData> =
    assessmentData.coverageComponents || assessmentData.coverage_components || {};

  const observations: Array<{
    category?: string;
    statement?: string;
    evidenceIds?: string[];
    evidence_ids?: string[];
  }> = assessmentData.observations || [];

  const interviewQuestions: string[] =
    assessmentData.suggestedInterviewQuestions ||
    assessmentData.suggested_interview_questions ||
    [];

  const repoUrl: string = repoMeta.url || "";
  const analyzedSha: string =
    report.analyzedCommitSha ||
    report.analyzed_commit_sha ||
    historyData.analyzedSha ||
    historyData.analyzed_sha ||
    "HEAD";
  const analysisTime: string = report.completedAt || report.completed_at || "";

  const contributors: ContributorData[] = historyData.contributors || [];
  const similarityMatches: SimilarityMatchData[] = similarityData.matches || [];
  const overallRatio: number =
    similarityData.overallSimilarityRatio ?? similarityData.overall_similarity_ratio ?? 0;

  return (
    <div className="min-h-screen bg-slate-50 flex flex-col pb-16">
      {/* Header Bar */}
      <header className="bg-white border-b border-slate-200 sticky top-0 z-20">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Link
              href="/"
              className="text-xs font-medium text-slate-500 hover:text-slate-800 border border-slate-200 rounded px-2.5 py-1"
            >
              ← Back to Dashboard
            </Link>
            <h1 className="text-base font-semibold text-slate-900 truncate">
              Evidence Report: {repoMeta.name || "Repository"}
            </h1>
          </div>

          <div className="text-xs text-slate-500 font-mono">
            Job #{jobId.substring(0, 8)}
          </div>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-8 flex-1 w-full space-y-6">
        {/* 1. Evidence Coverage & Overall Score */}
        <CoverageSummary
          score={coverageScore}
          status={assessmentStatus}
          components={coverageComponents}
        />

        {/* 2. Assessment Observations (Linked directly to supporting evidence) */}
        <div className="bg-white rounded-lg border border-slate-200 shadow-sm p-6" data-testid="observations-panel">
          <div className="border-b border-slate-100 pb-4 mb-5">
            <h3 className="text-base font-semibold text-slate-800">
              Assessment Observations & Signals ({observations.length})
            </h3>
            <p className="text-xs text-slate-500 mt-0.5">
              Specific findings derived strictly from inspectable repository facts. Each observation references atomic supporting evidence.
            </p>
          </div>

          {observations.length === 0 ? (
            <div className="p-4 bg-slate-50 border border-slate-200 rounded text-center text-xs text-slate-500">
              No specific automated observations recorded for this repository.
            </div>
          ) : (
            <ul className="space-y-3">
              {observations.map((obs, idx) => {
                const ids = obs.evidenceIds || obs.evidence_ids || [];

                return (
                  <li
                    key={idx}
                    className="p-4 rounded-md border border-slate-200 bg-slate-50/50 hover:bg-slate-50 transition-colors"
                  >
                    <div className="flex items-start justify-between gap-4">
                      <div className="space-y-1">
                        <span className="text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded bg-slate-200 text-slate-700">
                          {obs.category || "General Observation"}
                        </span>
                        <p className="text-xs text-slate-900 font-medium leading-relaxed pt-1">
                          {obs.statement}
                        </p>
                      </div>

                      {/* Supporting Evidence Link Anchors */}
                      {ids.length > 0 && (
                        <div className="flex flex-wrap gap-1.5 shrink-0">
                          {ids.map((evId) => (
                            <a
                              key={evId}
                              href={`#evidence-${evId}`}
                              className="text-[11px] font-mono font-semibold px-2 py-0.5 rounded bg-blue-50 text-blue-700 border border-blue-200 hover:bg-blue-100 hover:underline"
                              title={`Jump to evidence #${evId}`}
                            >
                              Evidence #{evId.substring(0, 6)}
                            </a>
                          ))}
                        </div>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        {/* 3. Concrete Interview Questions */}
        <div className="bg-white rounded-lg border border-slate-200 shadow-sm p-6" data-testid="interview-questions-panel">
          <div className="border-b border-slate-100 pb-4 mb-5">
            <h3 className="text-base font-semibold text-slate-800">
              Suggested Concrete Interview Questions ({interviewQuestions.length})
            </h3>
            <p className="text-xs text-slate-500 mt-0.5">
              Targeted technical discussion prompts to explore the candidate’s direct knowledge and architectural choices.
            </p>
          </div>

          {interviewQuestions.length === 0 ? (
            <div className="p-4 bg-slate-50 border border-slate-200 rounded text-center text-xs text-slate-500">
              No automated interview questions generated.
            </div>
          ) : (
            <ul className="space-y-3">
              {interviewQuestions.map((q, i) => (
                <li
                  key={i}
                  className="p-3.5 bg-blue-50/40 border border-blue-200/80 rounded-md text-xs text-slate-800 leading-relaxed flex items-start gap-3"
                >
                  <span className="font-bold text-blue-700 shrink-0">Q{i + 1}:</span>
                  <span>{q}</span>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* 4. Limitations and Boundaries Section */}
        {limitationsList.length > 0 && (
          <div className="bg-white rounded-lg border border-slate-200 shadow-sm p-6">
            <div className="border-b border-slate-100 pb-4 mb-4">
              <h3 className="text-base font-semibold text-slate-800">
                Evaluation Limitations & Uncertainty Boundaries
              </h3>
              <p className="text-xs text-slate-500 mt-0.5">
                Explicit constraints and unknown factors identified during automated review.
              </p>
            </div>
            <ul className="list-disc list-inside space-y-1.5 text-xs text-slate-600 bg-slate-50 p-4 rounded border border-slate-200">
              {limitationsList.map((lim, idx) => (
                <li key={idx} className="leading-relaxed">
                  {lim}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* 5. Git History Evidence */}
        <HistoryEvidence
          repositoryUrl={repoUrl}
          analyzedSha={analyzedSha}
          analysisTime={analysisTime}
          isFork={repoMeta.isFork ?? repoMeta.is_fork ?? false}
          parentUrl={repoMeta.parentUrl || repoMeta.parent_url}
          historyCompleteness={historyData}
          contributors={contributors}
          botCommitCount={historyData.botCommitCount ?? historyData.bot_commit_count ?? 0}
          mergeCommitCount={historyData.mergeCommitCount ?? historyData.merge_commit_count ?? 0}
        />

        {/* 6. Curated Reference Similarity */}
        <SimilarityEvidence
          overallRatio={overallRatio}
          matches={similarityMatches}
          coverageStatistics={similarityData.coverageStatistics || similarityData.coverage_statistics || {}}
          algorithmVersion={similarityData.algorithmVersion || similarityData.algorithm_version || "1.0.0"}
          limitations={similarityData.limitations || []}
          candidateRepoUrl={repoUrl}
          comparisonStatus={
            report.assessment?.coverageComponents?.reference_comparison?.status ||
            report.assessment?.coverage_components?.reference_comparison?.status ||
            (overallRatio !== null ? "complete" : "unavailable")
          }
        />

        {/* 7. Full Atomic Supporting Evidence Catalog */}
        <div id="evidence-catalog">
          <EvidenceList evidence={evidenceItems} />
        </div>
      </main>
    </div>
  );
}
