import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { ResumeUpload } from "../components/ResumeUpload";
import * as api from "../lib/api";

vi.mock("../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/api")>();
  return {
    ...actual,
    uploadResumeBatches: vi.fn(),
  };
});

describe("ResumeUpload Component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders accepted formats and limits before submission", () => {
    render(<ResumeUpload />);
    const notice = screen.getByTestId("upload-limits-notice");
    expect(notice).toBeInTheDocument();
    expect(notice).toHaveTextContent("PDF (.pdf)");
    expect(notice).toHaveTextContent("Microsoft Word (.docx)");
    expect(notice).toHaveTextContent("Up to 10 MB per file");
    expect(notice).toHaveTextContent("Text-based digital documents only");
  });

  it("handles upload success and invokes onUploadComplete callback", async () => {
    const mockOnComplete = vi.fn();
    const mockResponse: api.BatchUploadResponse = {
      total: 1,
      successful: [
        {
          filename: "alex_resume.pdf",
          status: "succeeded",
          candidateId: "11111111-1111-1111-1111-111111111111",
          projectsCount: 3,
        },
      ],
      failed: [],
    };

    vi.mocked(api.uploadResumeBatches).mockResolvedValueOnce(mockResponse);

    render(<ResumeUpload onUploadComplete={mockOnComplete} />);

    const file = new File(["dummy pdf content"], "alex_resume.pdf", {
      type: "application/pdf",
    });
    const fileInput = screen.getByLabelText(/Select Resume Files/i);

    fireEvent.change(fileInput, { target: { files: [file] } });

    const submitBtn = screen.getByRole("button", {
      name: /Upload & Extract \(1\)/i,
    });
    expect(submitBtn).toBeEnabled();

    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(api.uploadResumeBatches).toHaveBeenCalledWith([file]);
      expect(mockOnComplete).toHaveBeenCalledWith(mockResponse.successful);
    });

    // Check displayed results
    expect(screen.getByText("alex_resume.pdf")).toBeInTheDocument();
    expect(screen.getByText(/Projects found:/i)).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("handles partial batch failure and provides a clear manual-entry path for scanned resumes", async () => {
    const mockOnManualClick = vi.fn();
    const mockResponse: api.BatchUploadResponse = {
      total: 2,
      successful: [
        {
          filename: "valid_dev.pdf",
          status: "succeeded",
          candidateId: "22222222-2222-2222-2222-222222222222",
          projectsCount: 2,
        },
      ],
      failed: [
        {
          filename: "scanned_doc.pdf",
          status: "failed",
          error: "Scanned document detected: no selectable text found in PDF.",
          projectsCount: 0,
        },
      ],
    };

    vi.mocked(api.uploadResumeBatches).mockResolvedValueOnce(mockResponse);

    render(<ResumeUpload onManualEntryClick={mockOnManualClick} />);

    const file1 = new File(["pdf 1"], "valid_dev.pdf", { type: "application/pdf" });
    const file2 = new File(["pdf 2"], "scanned_doc.pdf", { type: "application/pdf" });

    const fileInput = screen.getByLabelText(/Select Resume Files/i);
    fireEvent.change(fileInput, { target: { files: [file1, file2] } });

    const submitBtn = screen.getByRole("button", {
      name: /Upload & Extract \(2\)/i,
    });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(screen.getByTestId("upload-results")).toBeInTheDocument();
    });

    // Verify success item
    expect(screen.getByText("valid_dev.pdf")).toBeInTheDocument();

    // Verify failed item and scanned resume notice
    expect(
      screen.getByText(/Scanned or image-only resume detected:/i)
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Automatic text extraction failed because no machine-readable text was found/i)
    ).toBeInTheDocument();

    const manualBtn = screen.getByRole("button", {
      name: /Add Candidate Manually/i,
    });
    expect(manualBtn).toBeInTheDocument();

    fireEvent.click(manualBtn);
    expect(mockOnManualClick).toHaveBeenCalled();
  });
});
