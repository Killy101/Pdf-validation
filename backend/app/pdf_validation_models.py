"""Contracts for the independent PDF source validator."""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator


PdfJurisdiction = Literal["auto", "au", "ca", "kr", "uk", "us", "nz", "jp", "sg", "eu", "other"]


class PdfValidationOptions(BaseModel):
    jurisdiction: PdfJurisdiction = "auto"
    workflow: Literal["current", "date_range"] = "current"
    date_start: date | None = None
    date_end: date | None = None
    history_url: str | None = Field(default=None, max_length=2048)
    archive_member: str | None = Field(default=None, min_length=1, max_length=2048)
    # content: the URL is the document (or a page that links it). reference: a landing page to search for it.
    source_mode: Literal["content", "reference"] = "content"

    @model_validator(mode="after")
    def validate_dates(self):
        if self.source_mode == "reference" and (self.workflow == "date_range" or self.archive_member):
            raise ValueError("A Reference URL finds the current document; use a Content URI for date ranges or ZIP members.")
        if self.workflow == "date_range":
            if self.archive_member:
                raise ValueError("Select archive documents within an individual historical version, not across a date range.")
            if not self.date_start or not self.date_end:
                raise ValueError("Choose both From date and To date for a historical comparison.")
            if self.date_start > self.date_end:
                raise ValueError("From date must be on or before To date.")
            if self.date_end > date.today():
                raise ValueError("Historical comparison dates cannot be in the future.")
        elif self.date_start or self.date_end or self.history_url:
            raise ValueError("Dates and version history URL require the date range workflow.")
        return self


class PdfReference(BaseModel):
    url: str
    label: str
    available: bool = True
    kind: Literal["pdf", "html", "zip"] = "pdf"
    archive_member: str | None = None


class PdfArchiveSource(BaseModel):
    url: str
    sha256: str
    member: str
    member_sha256: str
    unsupported_members: list[str] = Field(default_factory=list)


class PdfHistoricalReference(PdfReference):
    valid_from: date
    valid_to: date | None = None


class PdfFinding(BaseModel):
    kind: str
    severity: Literal["error", "warning", "info"]
    message: str
    pdf_page: int | None = None
    pdf_page_end: int | None = None
    approximate_location: bool = False
    source_page: int | None = None
    source_page_end: int | None = None
    source_heading: str | None = None
    source_archive_member: str | None = None
    source_url: str
    expected: str = ""
    actual: str = ""
    pdf_search_text: str = ""
    excerpt_truncated: bool = False
    expected_change: tuple[int, int] | None = None
    actual_change: tuple[int, int] | None = None
    action: str


class PdfLayoutEvidence(BaseModel):
    columns: int | None = None
    languages: list[str] = Field(default_factory=lambda: ["unknown"])
    parallel_bilingual: bool = False
    column_languages: list[str] = Field(default_factory=list)


class PdfDateEvidence(BaseModel):
    current_to: str | None = None
    creation_date: str | None = None
    modification_date: str | None = None


class PdfSourceSection(BaseModel):
    url: str
    label: str
    status: Literal["retrieved", "unavailable", "not_checked"]
    reason: str | None = None


class PdfSourceCoverage(BaseModel):
    method: str
    expected_sections: int | None = None
    retrieved_sections: int = 0
    pages_retrieved: int = 0
    complete: bool = False
    sections: list[PdfSourceSection] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class PdfDiscoveryStep(BaseModel):
    url: str
    label: str


class PdfDiscoveryItem(BaseModel):
    url: str
    label: str
    kind: Literal["pdf", "zip", "html", "other"]
    status: Literal["selected", "verified", "needs_verification", "rejected", "inaccessible", "unavailable", "visited", "not_relevant"]
    reason: str | None = None
    score: float | None = None
    depth: int | None = None
    path: list[PdfDiscoveryStep] = Field(default_factory=list)


class PdfDiscoveryTrail(BaseModel):
    start_url: str
    status: Literal["found", "needs_review", "not_found"]
    summary: str
    selected_url: str | None = None
    selected_label: str | None = None
    document_identity: str | None = None
    path: list[PdfDiscoveryStep] = Field(default_factory=list)
    pages_visited: int = 0
    browser_pages: int = 0
    items: list[PdfDiscoveryItem] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class PdfValidationResult(BaseModel):
    status: Literal["match", "mismatch", "needs_review", "unable"]
    summary: str
    comparison: Literal["exact_file", "content", "not_checked"] = "not_checked"
    filename: str
    submitted_url: str
    source_url: str
    source_type: Literal["pdf", "html", "zip", "unknown"] = "unknown"
    archive_source: PdfArchiveSource | None = None
    source_access_issue: Literal["captcha", "access_denied", "rate_limited", "unavailable"] | None = None
    checked_at: str
    upload_sha256: str
    source_sha256: str | None = None
    source_retrieved_at: str | None = None
    retrieval_attempts: int = 0
    document_identity: Literal["match", "mismatch", "needs_review", "not_checked"] = "not_checked"
    identity_summary: str | None = None
    identity_pdf_title: str | None = None
    identity_source_title: str | None = None
    comparison_language: str = "all"
    language_alignment: Literal["all_text", "selected", "needs_review"] = "all_text"
    pdf_layout: PdfLayoutEvidence | None = None
    source_layout: PdfLayoutEvidence | None = None
    scope_notes: list[str] = Field(default_factory=list)
    pdf_dates: PdfDateEvidence | None = None
    source_dates: PdfDateEvidence | None = None
    website_modified_on: str | None = None
    source_coverage: PdfSourceCoverage | None = None
    source_mode: Literal["content", "reference"] = "content"
    discovery: PdfDiscoveryTrail | None = None
    pdf_pages: int | None = None
    source_pages: int | None = None
    checked_pdf_pages: int = 0
    pdf_title: str | None = None
    source_title: str | None = None
    coverage_complete: bool = False
    findings_truncated: bool = False
    findings: list[PdfFinding] = Field(default_factory=list)
    references: list[PdfReference] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    jurisdiction: PdfJurisdiction = "auto"
    workflow: Literal["current", "date_range"] = "current"
    date_start: date | None = None
    date_end: date | None = None
    history_complete: bool = False
    versions: list[PdfVersionComparison] = Field(default_factory=list)


class PdfVersionComparison(BaseModel):
    reference: PdfHistoricalReference
    result: PdfValidationResult


PdfValidationResult.model_rebuild()


class PdfValidationConfiguration(BaseModel):
    max_upload_bytes: int
    max_files: int = Field(default=10, ge=1, le=10)
    max_pages: int
    timeout_seconds: float
    max_versions: int = Field(default=10, ge=1, le=20)


class PdfSourceRequest(PdfValidationOptions):
    content_uri: str = Field(min_length=1, max_length=2048)


class PdfBatchRequest(PdfSourceRequest):
    reference_url: str | None = Field(default=None, max_length=2048)


class PdfBatchResponse(BaseModel):
    batch_id: str
    expires_at: str


class PdfSourceDiscovery(BaseModel):
    source_url: str
    source_type: Literal["pdf", "html", "zip", "unknown"]
    summary: str
    source_title: str | None = None
    references: list[PdfReference] = Field(default_factory=list)
    jurisdiction: PdfJurisdiction = "auto"
    workflow: Literal["current", "date_range"] = "current"
    date_start: date | None = None
    date_end: date | None = None
    history_complete: bool = False
    versions: list[PdfHistoricalReference] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    source_mode: Literal["content", "reference"] = "content"
    discovery: PdfDiscoveryTrail | None = None


class PdfTextMatch(BaseModel):
    page: int
    count: int
    before: str
    match: str
    after: str


class PdfTextSearchResult(BaseModel):
    query: str
    pages_searched: int
    pages_with_text: int
    pages_matched: int
    total_matches: int
    truncated: bool = False
    matches: list[PdfTextMatch] = Field(default_factory=list)
