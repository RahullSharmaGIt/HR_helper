"use client";

import React, { useEffect, useRef, useState, useCallback } from "react";
import Link from "next/link";
import {
  getJobStatus,
  cancelJob,
  type AnalysisJobResponse,
} from "@/lib/api";

interface JobStatusProps {
  jobId: string;
  onJobComplete?: (job: AnalysisJobResponse) => void;
  onJobCanceled?: () => void;
  onRetry?: () => Promise<void>;
}

export function JobStatus({
  jobId,
  onJobComplete,
  onJobCanceled,
  onRetry,
}: JobStatusProps) {
  const [job, setJob] = useState<AnalysisJobResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isCanceling, setIsCanceling] = useState<boolean>(false);
  const [isRetrying, setIsRetrying] = useState<boolean>(false);

  // Polling management: bounded exponential backoff & stale response suppression
  const backoffDelayRef = useRef<number>(1000);
  const pollTimerRef = useRef<NodeJS.Timeout | null>(null);
  const activePollSeqRef = useRef<number>(0);
  const lastResolvedSeqRef = useRef<number>(0);
  const isMountedRef = useRef<boolean>(true);
  const isCancelingRef = useRef<boolean>(false);
  const isRetryingRef = useRef<boolean>(false);
  const currentJobIdRef = useRef<string>(jobId);

  currentJobIdRef.current = jobId;

  const isTerminalState = useCallback((status?: string): boolean => {
    return status === "succeeded" || status === "failed" || status === "canceled";
  }, []);

  const stopPolling = useCallback(() => {
    if (pollTimerRef.current) {
      clearTimeout(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }, []);

  const pollJob = useCallback(async () => {
    if (!isMountedRef.current) return;
    const targetJobId = jobId;
    const seq = ++activePollSeqRef.current;

    try {
      const data = await getJobStatus(targetJobId);

      // Discard stale responses if newer poll resolved, jobId changed, or component unmounted
      if (
        !isMountedRef.current ||
        targetJobId !== currentJobIdRef.current ||
        seq < lastResolvedSeqRef.current
      ) {
        return;
      }
      lastResolvedSeqRef.current = seq;

      setJob(data);
      setError(null);

      if (isTerminalState(data.status)) {
        stopPolling();
        if (data.status === "succeeded" && onJobComplete) {
          onJobComplete(data);
        } else if (data.status === "canceled" && onJobCanceled) {
          onJobCanceled();
        }
        return;
      }

      // Schedule next poll with bounded backoff
      backoffDelayRef.current = Math.min(backoffDelayRef.current * 1.5, 5000);
      pollTimerRef.current = setTimeout(pollJob, backoffDelayRef.current);
    } catch (err: unknown) {
      if (
        !isMountedRef.current ||
        targetJobId !== currentJobIdRef.current ||
        seq < lastResolvedSeqRef.current
      ) {
        return;
      }
      const msg = err instanceof Error ? err.message : "Failed to poll job status.";
      setError(msg);

      // Retry polling with backoff even on network hiccup
      backoffDelayRef.current = Math.min(backoffDelayRef.current * 1.5, 5000);
      pollTimerRef.current = setTimeout(pollJob, backoffDelayRef.current);
    }
  }, [jobId, isTerminalState, stopPolling, onJobComplete, onJobCanceled]);

  useEffect(() => {
    isMountedRef.current = true;
    backoffDelayRef.current = 1000;
    pollJob();

    return () => {
      isMountedRef.current = false;
      stopPolling();
    };
  }, [pollJob, stopPolling]);

  const handleCancel = async () => {
    if (isCancelingRef.current || !job) return;
    isCancelingRef.current = true;
    setIsCanceling(true);
    try {
      const canceled = await cancelJob(job.id);
      setJob(canceled);
      stopPolling();
      if (onJobCanceled) onJobCanceled();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to cancel job.";
      setError(msg);
    } finally {
      setIsCanceling(false);
      isCancelingRef.current = false;
    }
  };

  const handleRetry = async () => {
    if (isRetryingRef.current || !onRetry) return;
    isRetryingRef.current = true;
    setIsRetrying(true);
    setError(null);
    try {
      await onRetry();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Retry failed.";
      setError(msg);
    } finally {
      setIsRetrying(false);
      isRetryingRef.current = false;
    }
  };

  // Structured failure explanation
  const renderFailureDetail = () => {
    if (!job || job.status !== "failed") return null;

    let explanation = job.errorMessage || "Analysis failed during background execution.";
    if (job.failureCode === "GITHUB_RATE_LIMITED") {
      explanation = "GitHub API rate limit reached. Analysis paused to preserve quota.";
    } else if (job.failureCode === "REPO_NOT_FOUND") {
      explanation = "The selected public repository could not be located or is private.";
    } else if (job.failureCode === "METADATA_UNAVAILABLE") {
      explanation = "Repository metadata unavailable from upstream service.";
    } else if (job.failureCode === "WORKER_FAILED") {
      explanation = "Background analysis process terminated unexpectedly.";
    }

    return (
      <div
        role="alert"
        className="mt-4 p-4 bg-red-50 border border-red-200 rounded-xl text-xs text-red-900"
        data-testid="job-failure-detail"
      >
        <div className="font-semibold text-red-950">
          Failure Detail ({job.failureCode || "FAILED"}):
        </div>
        <p className="mt-1 leading-relaxed">{explanation}</p>
      </div>
    );
  };

  if (!job) {
    return (
      <div className="p-5 bg-white border border-slate-200 rounded-xl text-xs text-slate-500 animate-pulse mb-8">
        Initializing job status for {jobId}...
      </div>
    );
  }

  const statusColors: Record<string, string> = {
    queued: "bg-amber-100 text-amber-900 border-amber-200",
    running: "bg-blue-100 text-blue-900 border-blue-200",
    succeeded: "bg-emerald-100 text-emerald-900 border-emerald-200",
    failed: "bg-red-100 text-red-900 border-red-200",
    canceled: "bg-slate-100 text-slate-800 border-slate-300",
  };

  return (
    <section
      className="bg-white rounded-xl border border-slate-200 shadow-sm p-6 mb-10"
      data-purpose="step-3-job-status"
      data-testid="job-status-panel"
    >
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 pb-4 mb-4">
        <div>
          <div className="text-xs uppercase font-bold tracking-wider text-slate-400">Step 3</div>
          <h3 className="text-xl font-bold text-slate-900">
            3. Analysis Job Status
          </h3>
          <p className="text-xs text-slate-500 mt-0.5 font-mono">
            Job ID: {job.id}
          </p>
        </div>
        <span
          className={`text-xs px-3 py-1 rounded-full uppercase font-bold tracking-wider border ${
            statusColors[job.status] || "bg-slate-100 text-slate-800"
          }`}
          data-testid="job-status-badge"
        >
          {job.status}
        </span>
      </div>

      {error && (
        <div
          role="alert"
          className="p-3 mb-4 bg-red-50 border border-red-200 rounded-xl text-xs text-red-700"
        >
          {error}
        </div>
      )}

      {/* Progress & Stage */}
      <div className="space-y-2 mb-4">
        <div className="flex justify-between text-xs font-medium text-slate-600">
          <span>
            Current Stage:{" "}
            <strong className="text-slate-900 uppercase font-mono">
              {job.stage || "pending"}
            </strong>
          </span>
          <span className="font-mono font-bold text-slate-900">{job.progress}%</span>
        </div>
        <div className="w-full bg-slate-100 rounded-full h-2.5 overflow-hidden">
          <div
            className={`h-2.5 rounded-full transition-all duration-300 ${
              job.status === "failed"
                ? "bg-red-500"
                : job.status === "succeeded"
                ? "bg-emerald-600"
                : "bg-slate-900"
            }`}
            style={{ width: `${Math.max(job.progress, 5)}%` }}
          />
        </div>
      </div>

      {renderFailureDetail()}

      {/* Action Controls */}
      <div className="flex flex-wrap items-center justify-between gap-4 pt-4 border-t border-slate-100 mt-4">
        <div className="text-xs text-slate-500">
          {job.status === "running" && "Analysis running across Git history and reference catalog..."}
          {job.status === "queued" && "Waiting for background worker capacity..."}
          {job.status === "succeeded" && "Analysis complete. Evidence ready for review."}
          {job.status === "canceled" && "Job canceled by administrator."}
        </div>

        <div className="flex items-center gap-3">
          {(job.status === "running" || job.status === "queued") && (
            <button
              type="button"
              onClick={handleCancel}
              disabled={isCanceling}
              className="px-3.5 py-2 border border-red-300 text-red-700 hover:bg-red-50 rounded-lg text-xs font-semibold shadow-xs disabled:opacity-50 transition"
              data-testid="cancel-job-button"
            >
              {isCanceling ? "Canceling..." : "Cancel Job"}
            </button>
          )}

          {job.status === "failed" && onRetry && (
            <button
              type="button"
              onClick={handleRetry}
              disabled={isRetrying}
              className="px-4 py-2 bg-slate-900 hover:bg-slate-800 text-white rounded-lg text-xs font-semibold shadow-xs disabled:opacity-50 transition"
              data-testid="retry-job-button"
            >
              {isRetrying ? "Retrying..." : "Retry Analysis"}
            </button>
          )}

          {job.status === "succeeded" && (
            <Link
              href={`/analyses/${job.id}`}
              className="px-5 py-2 bg-slate-900 hover:bg-slate-800 text-white rounded-lg text-xs font-semibold shadow-xs inline-flex items-center gap-1.5 transition"
            >
              <span>View Evidence Report</span>
              <svg className="w-4 h-4 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path d="M14 5l7 7m0 0l-7 7m7-7H3" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" />
              </svg>
            </Link>
          )}
        </div>
      </div>
    </section>
  );
}
