"use client";

import React, { useState } from "react";
import { uploadResumeBatches, type BatchUploadItem } from "@/lib/api";

interface ResumeUploadProps {
  onUploadComplete?: (items: BatchUploadItem[]) => void;
  onManualEntryClick?: () => void;
}

export function ResumeUpload({
  onUploadComplete,
  onManualEntryClick,
}: ResumeUploadProps) {
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [isUploading, setIsUploading] = useState<boolean>(false);
  const [uploadResults, setUploadResults] = useState<BatchUploadItem[] | null>(null);
  const [generalError, setGeneralError] = useState<string | null>(null);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      const filesArray = Array.from(e.target.files);
      setSelectedFiles(filesArray);
      setUploadResults(null);
      setGeneralError(null);
    }
  };

  const handleRemoveFile = (index: number) => {
    setSelectedFiles((prev) => prev.filter((_, i) => i !== index));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (selectedFiles.length === 0) return;

    setIsUploading(true);
    setGeneralError(null);
    setUploadResults(null);

    try {
      const response = await uploadResumeBatches(selectedFiles);
      const allItems: BatchUploadItem[] = [
        ...(response.successful || []),
        ...(response.failed || []),
      ];
      setUploadResults(allItems);
      setSelectedFiles([]);
      if (onUploadComplete) {
        onUploadComplete(allItems);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to upload resume batch.";
      setGeneralError(msg);
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <div className="bg-white rounded-lg border border-slate-200 shadow-sm p-6 mb-8">
      <div className="border-b border-slate-100 pb-4 mb-5">
        <h2 className="text-xl font-semibold text-slate-800">
          Upload Candidate Resumes
        </h2>
        <p className="text-sm text-slate-500 mt-1">
          Upload resumes to extract candidate profiles, declared projects, and public repository candidates.
        </p>
      </div>

      {/* Pre-submission limits & accepted formats */}
      <div
        className="bg-slate-50 border border-slate-200 rounded-md p-4 mb-6 text-sm text-slate-700 space-y-1"
        data-testid="upload-limits-notice"
      >
        <div className="font-medium text-slate-900">Supported Formats & Limits:</div>
        <ul className="list-disc list-inside space-y-0.5 text-xs text-slate-600">
          <li><strong>Accepted Formats:</strong> PDF (<code>.pdf</code>) and Microsoft Word (<code>.docx</code>)</li>
          <li><strong>File Size Limit:</strong> Up to 10 MB per file, max 10 files per batch</li>
          <li><strong>Requirement:</strong> Text-based digital documents only. Image-only or scanned PDFs are unsupported and require manual project entry.</li>
        </ul>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label
            htmlFor="resume-files"
            className="block text-sm font-medium text-slate-700 mb-1"
          >
            Select Resume Files
          </label>
          <input
            id="resume-files"
            type="file"
            multiple
            accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            onChange={handleFileChange}
            disabled={isUploading}
            aria-describedby="file-upload-help"
            className="block w-full text-sm text-slate-500 file:mr-4 file:py-2.5 file:px-4 file:rounded-md file:border-0 file:text-sm file:font-semibold file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100 cursor-pointer border border-slate-300 rounded-md p-1 focus:ring-2 focus:ring-blue-500 focus:outline-none"
          />
          <span id="file-upload-help" className="sr-only">
            Select one or more PDF or DOCX resume files under 10 megabytes.
          </span>
        </div>

        {/* Selected files preview */}
        {selectedFiles.length > 0 && (
          <div className="space-y-2">
            <div className="text-xs font-semibold uppercase tracking-wider text-slate-500">
              Selected Files ({selectedFiles.length})
            </div>
            <ul className="divide-y divide-slate-100 border border-slate-200 rounded-md overflow-hidden bg-slate-50">
              {selectedFiles.map((file, idx) => (
                <li
                  key={`${file.name}-${idx}`}
                  className="px-3 py-2 flex items-center justify-between text-xs"
                >
                  <span className="font-mono text-slate-800 truncate max-w-md">
                    {file.name}
                  </span>
                  <div className="flex items-center gap-3">
                    <span className="text-slate-500">
                      {(file.size / 1024).toFixed(1)} KB
                    </span>
                    <button
                      type="button"
                      onClick={() => handleRemoveFile(idx)}
                      disabled={isUploading}
                      className="text-red-600 hover:text-red-800 font-medium disabled:opacity-50"
                      aria-label={`Remove file ${file.name}`}
                    >
                      Remove
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}

        {generalError && (
          <div
            role="alert"
            className="p-3 bg-red-50 border border-red-200 rounded-md text-sm text-red-700"
          >
            {generalError}
          </div>
        )}

        <div className="flex items-center gap-4 pt-2">
          <button
            type="submit"
            disabled={isUploading || selectedFiles.length === 0}
            aria-busy={isUploading}
            className="px-5 py-2.5 bg-blue-600 hover:bg-blue-700 text-white font-medium text-sm rounded-md shadow-sm transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
          >
            {isUploading ? (
              <>
                <svg
                  className="animate-spin -ml-1 mr-2 h-4 w-4 text-white"
                  fill="none"
                  viewBox="0 0 24 24"
                  aria-hidden="true"
                >
                  <circle
                    className="opacity-25"
                    cx="12"
                    cy="12"
                    r="10"
                    stroke="currentColor"
                    strokeWidth="4"
                  />
                  <path
                    className="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8v8H4z"
                  />
                </svg>
                Processing Resumes...
              </>
            ) : (
              `Upload & Extract (${selectedFiles.length})`
            )}
          </button>

          {onManualEntryClick && (
            <button
              type="button"
              onClick={onManualEntryClick}
              className="text-sm font-medium text-slate-600 hover:text-slate-900 border border-slate-300 rounded-md px-4 py-2.5 bg-white hover:bg-slate-50"
            >
              Manual Entry Path
            </button>
          )}
        </div>
      </form>

      {/* Batch Upload Results */}
      {uploadResults && uploadResults.length > 0 && (
        <div className="mt-8 border-t border-slate-200 pt-6" data-testid="upload-results">
          <h3 className="text-base font-semibold text-slate-800 mb-3">
            Batch Processing Results
          </h3>
          <ul className="space-y-3">
            {uploadResults.map((item, idx) => {
              const isSuccess = item.status === "succeeded";
              const isScannedOrUnreadable =
                !isSuccess &&
                item.error &&
                (item.error.toLowerCase().includes("scanned") ||
                  item.error.toLowerCase().includes("selectable text") ||
                  item.error.toLowerCase().includes("image") ||
                  item.error.toLowerCase().includes("empty"));

              return (
                <li
                  key={`${item.filename}-${idx}`}
                  className={`p-4 rounded-md border text-sm ${
                    isSuccess
                      ? "bg-green-50/70 border-green-200 text-green-950"
                      : "bg-red-50/70 border-red-200 text-red-950"
                  }`}
                >
                  <div className="flex items-center justify-between font-medium">
                    <span className="font-mono text-xs">{item.filename}</span>
                    <span
                      className={`text-xs px-2 py-0.5 rounded-full uppercase font-bold tracking-wide ${
                        isSuccess
                          ? "bg-green-200 text-green-900"
                          : "bg-red-200 text-red-900"
                      }`}
                    >
                      {item.status}
                    </span>
                  </div>

                  {isSuccess ? (
                    <div className="mt-2 text-xs text-green-800 flex items-center gap-4">
                      <span>Status: <strong>Extracted successfully</strong></span>
                      <span>Projects found: <strong>{item.projectsCount}</strong></span>
                    </div>
                  ) : (
                    <div className="mt-2 text-xs text-red-800">
                      <div>Error: {item.error || "Extraction failed"}</div>

                      {/* Explicit Manual-entry path for unsupported scanned resumes */}
                      {isScannedOrUnreadable && (
                        <div className="mt-3 p-3 bg-white/80 border border-amber-300 rounded text-amber-900">
                          <p className="font-medium">
                            Scanned or image-only resume detected:
                          </p>
                          <p className="mt-0.5 text-xs text-amber-800">
                            Automatic text extraction failed because no machine-readable text was found.
                            Use the manual-entry path to add this candidate and their declared project details.
                          </p>
                          {onManualEntryClick && (
                            <button
                              type="button"
                              onClick={onManualEntryClick}
                              className="mt-2 text-xs font-semibold bg-amber-600 hover:bg-amber-700 text-white px-3 py-1.5 rounded shadow-sm"
                            >
                              Add Candidate Manually
                            </button>
                          )}
                        </div>
                      )}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}
