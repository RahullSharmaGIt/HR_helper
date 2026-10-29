import React from "react";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { ProjectSelector } from "../components/ProjectSelector";
import { RepositorySelector } from "../components/RepositorySelector";
import { JobStatus } from "../components/JobStatus";
import * as api from "../lib/api";

vi.mock("../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/api")>();
  return {
    ...actual,
    getJobStatus: vi.fn(),
    cancelJob: vi.fn(),
  };
});

describe("ProjectSelector & RepositorySelector Requirements", () => {
  const dummyProjects: api.ProjectSummary[] = [
    {
      id: "p1",
      candidateId: "c1",
      name: "Key-Value Engine",
      description: "LSM tree in Rust",
      isSelected: false,
      explicitGithubUrls: ["https://github.com/candidate/kv-engine"],
      createdAt: new Date().toISOString(),
    },
    {
      id: "p2",
      candidateId: "c1",
      name: "Raft Consensus",
      description: "Distributed consensus algorithm",
      isSelected: false,
      explicitGithubUrls: [],
      createdAt: new Date().toISOString(),
    },
  ];

  it("enforces single project selection and displays extracted resume links separately", () => {
    const handleSelect = vi.fn();
    render(
      <ProjectSelector
        candidateId="c1"
        projects={dummyProjects}
        selectedProjectId="p1"
        onSelectProject={handleSelect}
      />
    );

    // Verify extracted resume links are clearly separated
    expect(screen.getByText(/Extracted Resume Link:/i)).toBeInTheDocument();
    expect(screen.getByText("https://github.com/candidate/kv-engine")).toBeInTheDocument();

    // Verify selecting second project calls onSelectProject
    const p2Radio = screen.getByLabelText(/Raft Consensus/i);
    fireEvent.click(p2Radio);
    expect(handleSelect).toHaveBeenCalledWith("p2");
  });

  it("requires explicit repository confirmation before enabling analysis and protects against duplicate clicks", async () => {
    const dummyRepos: api.RepositorySelectionResponse[] = [
      {
        id: "r1",
        projectId: "p1",
        owner: "candidate",
        name: "kv-engine",
        url: "https://github.com/candidate/kv-engine",
        discoveryReason: "Name and technology match",
        confidenceCategory: "high",
        isConfirmed: false,
        createdAt: new Date().toISOString(),
      },
    ];

    const mockConfirm = vi.fn().mockImplementation(() => new Promise((resolve) => setTimeout(resolve, 50)));
    const mockTrigger = vi.fn().mockImplementation(() => new Promise((resolve) => setTimeout(resolve, 50)));

    const { rerender } = render(
      <RepositorySelector
        projectId="p1"
        repositories={dummyRepos}
        onConfirmRepository={mockConfirm}
        onTriggerAnalysis={mockTrigger}
        hasActiveJob={false}
      />
    );

    // Analysis trigger must be disabled prior to confirmation
    const triggerBtn = screen.getByRole("button", {
      name: /Trigger Evidence Analysis/i,
    });
    expect(triggerBtn).toBeDisabled();

    // Confirm repository
    const confirmBtn = screen.getByRole("button", {
      name: /Confirm Selected Repository/i,
    });
    expect(confirmBtn).toBeEnabled();

    // Test duplicate clicks protection on Confirm button
    fireEvent.click(confirmBtn);
    fireEvent.click(confirmBtn);
    expect(confirmBtn).toBeDisabled();

    await waitFor(() => {
      expect(mockConfirm).toHaveBeenCalledTimes(1);
    });

    // Re-render with confirmed repository
    const confirmedRepos = [{ ...dummyRepos[0], isConfirmed: true }];
    rerender(
      <RepositorySelector
        projectId="p1"
        repositories={confirmedRepos}
        onConfirmRepository={mockConfirm}
        onTriggerAnalysis={mockTrigger}
        hasActiveJob={false}
      />
    );

    // Trigger button should now be enabled
    expect(triggerBtn).toBeEnabled();

    // Test duplicate click protection on Trigger Analysis button
    fireEvent.click(triggerBtn);
    fireEvent.click(triggerBtn);
    expect(triggerBtn).toBeDisabled();

    await waitFor(() => {
      expect(mockTrigger).toHaveBeenCalledTimes(1);
    });
  });
});

describe("JobStatus: Polling, Cancellation & Stale Response Handling", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("polls running job with bounded backoff and stops at terminal succeeded state", async () => {
    const onComplete = vi.fn();
    const runningJob: api.AnalysisJobResponse = {
      id: "j1",
      repositorySelectionId: "r1",
      status: "running",
      stage: "fetch",
      progress: 30,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };
    const succeededJob: api.AnalysisJobResponse = {
      ...runningJob,
      status: "succeeded",
      stage: "persistence",
      progress: 100,
    };

    vi.mocked(api.getJobStatus)
      .mockResolvedValueOnce(runningJob)
      .mockResolvedValueOnce(succeededJob);

    render(<JobStatus jobId="j1" onJobComplete={onComplete} />);

    // Initial poll
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(screen.getByText("running")).toBeInTheDocument();
    expect(screen.getByText("30%")).toBeInTheDocument();

    // Advance backoff timer for second poll
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1500);
    });

    expect(screen.getByText("succeeded")).toBeInTheDocument();
    expect(screen.getByText("100%")).toBeInTheDocument();
    expect(onComplete).toHaveBeenCalledWith(succeededJob);

    // Verify polling stopped: advancing timer further does not trigger additional getJobStatus calls
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10000);
    });
    expect(api.getJobStatus).toHaveBeenCalledTimes(2);
  });

  it("allows administrator cancellation with duplicate-click protection", async () => {
    const onCanceled = vi.fn();
    const runningJob: api.AnalysisJobResponse = {
      id: "j2",
      repositorySelectionId: "r1",
      status: "running",
      stage: "similarity",
      progress: 60,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };
    const canceledJob: api.AnalysisJobResponse = {
      ...runningJob,
      status: "canceled",
    };

    vi.mocked(api.getJobStatus).mockResolvedValue(runningJob);
    vi.mocked(api.cancelJob).mockImplementation(
      () => new Promise((resolve) => setTimeout(() => resolve(canceledJob), 50))
    );

    render(<JobStatus jobId="j2" onJobCanceled={onCanceled} />);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    const cancelBtn = screen.getByTestId("cancel-job-button");
    expect(cancelBtn).toBeInTheDocument();

    // Trigger immediate duplicate clicks
    fireEvent.click(cancelBtn);
    fireEvent.click(cancelBtn);

    expect(api.cancelJob).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(60);
    });

    expect(screen.getByText("canceled")).toBeInTheDocument();
    expect(onCanceled).toHaveBeenCalled();
  });

  it("discards stale responses when superseded by a newer job", async () => {
    let resolveSlowPoll: (val: api.AnalysisJobResponse) => void = () => {};
    const slowPollPromise = new Promise<api.AnalysisJobResponse>((resolve) => {
      resolveSlowPoll = resolve;
    });

    const fastJobResult: api.AnalysisJobResponse = {
      id: "j4",
      repositorySelectionId: "r1",
      status: "running",
      stage: "assessment",
      progress: 85,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };

    const staleJobResult: api.AnalysisJobResponse = {
      id: "j3",
      repositorySelectionId: "r1",
      status: "running",
      stage: "fetch",
      progress: 20,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };

    // First call (job j3) returns slow promise
    // Second call (job j4) returns fast result
    vi.mocked(api.getJobStatus)
      .mockReturnValueOnce(slowPollPromise)
      .mockResolvedValueOnce(fastJobResult);

    const { rerender } = render(<JobStatus jobId="j3" />);

    // Switch to job j4 while j3 is still in-flight
    rerender(<JobStatus jobId="j4" />);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    // j4 resolved with 85%
    expect(screen.getByText("85%")).toBeInTheDocument();

    // Now resolve the stale j3 poll
    await act(async () => {
      resolveSlowPoll(staleJobResult);
      await vi.advanceTimersByTimeAsync(0);
    });

    // Stale 20% response from j3 must be discarded
    expect(screen.getByText("85%")).toBeInTheDocument();
    expect(screen.queryByText("20%")).not.toBeInTheDocument();
  });
});
