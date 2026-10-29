import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { CoverageSummary } from "../components/CoverageSummary";
import { HistoryEvidence } from "../components/HistoryEvidence";
import { SimilarityEvidence } from "../components/SimilarityEvidence";
import { EvidenceList } from "../components/EvidenceList";

describe("Evidence Report Interface Tests", () => {
  it("displays mandatory disclaimer prominently and labels score as Evidence coverage", () => {
    render(
      <CoverageSummary
        score={78}
        status="reviewable"
        components={{
          history_availability: {
            score: 100,
            weight: 0.3,
            status: "complete",
          },
        }}
      />
    );

    // Exact mandatory disclaimer sentence
    expect(
      screen.getByText(/These findings are signals for human review, not proof of authorship or misconduct\./i)
    ).toBeInTheDocument();

    // Evidence coverage label
    expect(screen.getByText(/Evidence coverage:/i)).toBeInTheDocument();
    expect(screen.getByText("78 / 100")).toBeInTheDocument();
  });

  it("handles partial reports and displays unknown measurements as Unavailable with reasons", () => {
    render(
      <CoverageSummary
        score={45}
        status="limited_evidence"
        components={{
          history_availability: {
            score: 0,
            weight: 0.3,
            status: "unavailable",
            reason: "Repository contains 0 reachable commits.",
          },
          source_inspection: {
            score: null,
            weight: 0.25,
            status: "unavailable",
            reason: "No source files in supported languages found.",
          },
        }}
      />
    );

    expect(screen.getByText("Repository contains 0 reachable commits.")).toBeInTheDocument();
    expect(screen.getByText("No source files in supported languages found.")).toBeInTheDocument();
    const unavailables = screen.getAllByText("Unavailable");
    expect(unavailables.length).toBeGreaterThan(0);
  });

  it("handles empty references gracefully", () => {
    render(
      <SimilarityEvidence
        overallRatio={0}
        matches={[]}
        limitations={["Configured reference collection is empty."]}
      />
    );

    expect(
      screen.getByText("No significant code similarity detected against the configured reference collection.")
    ).toBeInTheDocument();
    expect(screen.getByText("Configured reference collection is empty.")).toBeInTheDocument();
  });

  it("handles extremely long paths with accessible break-all text wrapping", () => {
    const veryLongPath =
      "packages/core/src/enterprise/subsystems/distributed_transaction_coordinator_state_machine_v2_impl.ts";

    render(
      <SimilarityEvidence
        overallRatio={0.35}
        matches={[
          {
            candidatePath: veryLongPath,
            referenceRepoUrl: "https://github.com/reference-catalog/coordinator",
            referenceCommitSha: "abcdef1234567890",
            similarityRatio: 0.35,
          },
        ]}
      />
    );

    const pathElement = screen.getByText(veryLongPath);
    expect(pathElement).toBeInTheDocument();
    expect(pathElement).toHaveClass("break-all");
  });

  it("ensures external links use target='_blank' and rel='noopener noreferrer'", () => {
    const testUrl = "https://github.com/candidate-user/verified-repo";
    render(
      <HistoryEvidence
        repositoryUrl={testUrl}
        analyzedSha="1a2b3c4d5e6f"
        isFork={true}
        parentUrl="https://github.com/upstream-org/original-repo"
      />
    );

    const repoLink = screen.getByRole("link", { name: testUrl });
    expect(repoLink).toHaveAttribute("target", "_blank");
    expect(repoLink).toHaveAttribute("rel", "noopener noreferrer");

    const parentLink = screen.getByRole("link", {
      name: /Upstream: https:\/\/github\.com\/upstream-org\/original-repo/i,
    });
    expect(parentLink).toHaveAttribute("target", "_blank");
    expect(parentLink).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("renders atomic evidence items with linkable ID anchors", () => {
    const dummyEvidence = [
      {
        id: "ev-uuid-1234",
        kind: "git_history",
        summary: "Analyzed 42 commits from 2 contributors.",
        sourceUrl: "https://github.com/org/repo/commits",
        commitSha: "111122223333",
      },
    ];

    render(<EvidenceList evidence={dummyEvidence} />);

    const item = screen.getByTestId("evidence-item-ev-uuid-1234");
    expect(item).toBeInTheDocument();
    expect(item).toHaveAttribute("id", "evidence-ev-uuid-1234");
    expect(screen.getByText("Analyzed 42 commits from 2 contributors.")).toBeInTheDocument();
  });
});
