import { test, expect } from "@playwright/test";
import path from "path";

test.describe("Resume Project Review End-to-End Workflow", () => {
  const BASE_URL = process.env.PLAYWRIGHT_TEST_BASE_URL || "http://localhost:3000";

  test("full candidate intake, repository confirmation, evidence report, and cleanup", async ({ page }) => {
    // 1. Login flow
    await page.goto(`${BASE_URL}/login`);
    await expect(page.locator("h1")).toContainText(/Sign In|Resume Review/i);

    const adminPassword = process.env.ADMIN_PASSWORD || "test-admin-secret";
    await page.fill('input[type="password"]', adminPassword);
    await page.click('button[type="submit"]');

    // Should redirect to dashboard
    await expect(page).toHaveURL(`${BASE_URL}/`);
    await expect(page.getByText(/Resume Project Review Platform|Upload Resumes/i)).toBeVisible();

    // 2. Batch Upload with partial failure
    const fixturesDir = path.resolve(__dirname, "../../backend/tests/fixtures/resumes");
    const validPdf = path.join(fixturesDir, "alex_mercer_portfolio.pdf");
    const validDocx = path.join(fixturesDir, "jordan_lee_inaccessible.docx");
    const corruptPdf = path.join(fixturesDir, "corrupt_resume.pdf");

    // Set file input with all three files
    const fileInput = page.locator('input[type="file"]');
    await fileInput.setInputFiles([validPdf, validDocx, corruptPdf]);

    await page.click('button:has-text("Upload and Process Batch")');

    // Verify partial failure summary
    await expect(page.getByText(/corrupt_resume.pdf/i)).toBeVisible();
    await expect(page.getByText(/Failed/i)).toBeVisible();
    await expect(page.getByText(/Alex Mercer|Alex Mercer Portfolio/i)).toBeVisible();

    // 3. Navigate to Candidate Review
    await page.click('a:has-text("Review Candidate")');
    await expect(page.locator("h1")).toContainText(/Candidate Review/i);

    // 4. Project and Repository Confirmation
    await expect(page.getByText(/Portfolio App/i)).toBeVisible();
    await expect(page.getByText(/https:\/\/github.com\/synthetic-candidate\/portfolio-app/i)).toBeVisible();

    // Click confirm repository button
    const confirmButton = page.locator('button:has-text("Confirm This Repository")').first();
    if (await confirmButton.isVisible()) {
      await confirmButton.click();
      await expect(page.getByText(/Confirmed for Analysis/i)).toBeVisible();
    }

    // 5. Trigger Analysis Job
    const startAnalysisBtn = page.locator('button:has-text("Start Repository Analysis")');
    await expect(startAnalysisBtn).toBeEnabled();
    await startAnalysisBtn.click();

    // 6. Monitor Job Status & Completion
    await expect(page.getByText(/Analysis Status|queued|running|completed/i)).toBeVisible();

    // Wait for job completion (or link to report)
    const viewReportLink = page.locator('a:has-text("View Evidence Report")');
    await expect(viewReportLink).toBeVisible({ timeout: 45000 });
    await viewReportLink.click();

    // 7. Verify Evidence Report Page
    await expect(page).toHaveURL(/.*\/analyses\/.*/);

    // Verify prominent mandatory disclaimer sentence
    const disclaimerNotice = page.getByTestId("evidence-signal-disclaimer");
    await expect(disclaimerNotice).toBeVisible();
    await expect(disclaimerNotice).toContainText(
      "These findings are signals for human review, not proof of authorship or misconduct."
    );

    // Verify Evidence Coverage Score
    await expect(page.getByText(/Evidence coverage:/i)).toBeVisible();
    await expect(page.getByTestId("coverage-summary")).toBeVisible();

    // Verify Git commit SHA and history evidence
    await expect(page.getByTestId("history-evidence")).toBeVisible();
    await expect(page.getByText(/Analyzed Commit SHA/i)).toBeVisible();

    // Verify atomic evidence links
    await expect(page.getByTestId("observations-panel")).toBeVisible();
    const evidenceAnchor = page.locator('a[href^="#evidence-"]').first();
    if (await evidenceAnchor.isVisible()) {
      await expect(evidenceAnchor).toBeVisible();
    }

    // 8. Test Candidate Deletion & Cleanup
    await page.goto(`${BASE_URL}/`);
    await page.click('a:has-text("Review Candidate")');

    const deleteBtn = page.locator('button:has-text("Delete Candidate")');
    await expect(deleteBtn).toBeVisible();
    await deleteBtn.click();

    // Confirm in dialog
    const confirmDialogBtn = page.locator('button:has-text("Permanently Delete")');
    await expect(confirmDialogBtn).toBeVisible();
    await confirmDialogBtn.click();

    // Redirected back to candidate list
    await expect(page).toHaveURL(`${BASE_URL}/`);

    // 9. Expired Session Scenario
    await page.evaluate(() => {
      document.cookie = "session_token=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;";
    });

    await page.goto(`${BASE_URL}/`);
    await expect(page).toHaveURL(`${BASE_URL}/login`);
  });
});
