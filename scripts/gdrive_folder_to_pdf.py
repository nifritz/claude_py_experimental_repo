#!/usr/bin/env python3
"""
gdrive_folder_to_pdf.py

Converts all files in a Google Drive folder to a single merged PDF,
then uploads the result to a destination Google Drive folder.

Usage:
    python scripts/gdrive_folder_to_pdf.py \
        --src "https://drive.google.com/drive/folders/SOURCE_FOLDER_ID" \
        --dst "https://drive.google.com/drive/folders/DEST_FOLDER_ID" \
        --output "merged.pdf" \
        --credentials credentials.json \
        --token token.json

Environment variables (alternative to CLI flags):
    GDRIVE_CREDENTIALS_FILE  Path to OAuth2 credentials JSON
    GDRIVE_TOKEN_FILE        Path to stored token JSON
"""

import argparse
import io
import logging
import os
import re
import sys
import tempfile
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
import pypdf

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/drive.file",
]

# MIME types that Google Drive can export as PDF
EXPORTABLE_MIME_TYPES: dict[str, str] = {
    "application/vnd.google-apps.document": "application/pdf",
    "application/vnd.google-apps.spreadsheet": "application/pdf",
    "application/vnd.google-apps.presentation": "application/pdf",
    "application/vnd.google-apps.drawing": "application/pdf",
}

# MIME types that are already PDF or binary and can be downloaded directly
DIRECT_PDF_MIME = "application/pdf"


def extract_folder_id(url_or_id: str) -> str:
    """Extract a Drive folder ID from a URL or return as-is if already an ID."""
    match = re.search(r"/folders/([a-zA-Z0-9_-]+)", url_or_id)
    if match:
        return match.group(1)
    # If it looks like a plain ID (no slashes), return it directly
    if re.fullmatch(r"[a-zA-Z0-9_-]+", url_or_id):
        return url_or_id
    raise ValueError(f"Cannot extract folder ID from: {url_or_id!r}")


def authenticate(credentials_file: str, token_file: str) -> Credentials:
    """Load or refresh OAuth2 credentials, running the flow if necessary."""
    creds: Credentials | None = None

    if Path(token_file).exists():
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            log.info("Refreshing access token...")
            creds.refresh(Request())
        else:
            log.info("Starting OAuth2 flow (browser will open)...")
            flow = InstalledAppFlow.from_client_secrets_file(credentials_file, SCOPES)
            creds = flow.run_local_server(port=0)

        Path(token_file).write_text(creds.to_json())
        log.info("Token saved to %s", token_file)

    return creds


def list_files_in_folder(service, folder_id: str) -> list[dict]:
    """Return all files in a Drive folder, sorted by name."""
    query = f"'{folder_id}' in parents and trashed = false"
    fields = "files(id, name, mimeType)"
    results = []
    page_token = None

    while True:
        resp = service.files().list(
            q=query,
            fields=f"nextPageToken, {fields}",
            orderBy="name",
            pageToken=page_token,
        ).execute()
        results.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    return results


def file_to_pdf_bytes(service, file: dict) -> bytes | None:
    """Download or export a Drive file as PDF bytes. Returns None if unsupported."""
    mime = file["mimeType"]
    fid = file["id"]
    name = file["name"]

    if mime in EXPORTABLE_MIME_TYPES:
        log.info("Exporting '%s' (%s) as PDF", name, mime)
        request = service.files().export_media(fileId=fid, mimeType="application/pdf")
    elif mime == DIRECT_PDF_MIME:
        log.info("Downloading '%s' (already PDF)", name)
        request = service.files().get_media(fileId=fid)
    else:
        log.warning("Skipping '%s' — unsupported MIME type: %s", name, mime)
        return None

    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buf.getvalue()


def merge_pdfs(pdf_bytes_list: list[bytes]) -> bytes:
    """Merge a list of PDF byte strings into a single PDF."""
    writer = pypdf.PdfWriter()
    for pdf_bytes in pdf_bytes_list:
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        for page in reader.pages:
            writer.add_page(page)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def upload_pdf(service, pdf_bytes: bytes, filename: str, folder_id: str) -> dict:
    """Upload a PDF to a Drive folder and return the file metadata."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp_path = tmp.name

    try:
        metadata = {"name": filename, "parents": [folder_id]}
        media = MediaFileUpload(tmp_path, mimetype="application/pdf", resumable=True)
        uploaded = service.files().create(
            body=metadata, media_body=media, fields="id, name, webViewLink"
        ).execute()
        log.info("Uploaded '%s' → %s", uploaded["name"], uploaded["webViewLink"])
        return uploaded
    finally:
        os.unlink(tmp_path)


def run(src_url: str, dst_url: str, output_name: str, credentials_file: str, token_file: str) -> dict:
    """
    Main entry point. Returns the uploaded file metadata dict.

    Args:
        src_url:          Google Drive folder URL (source)
        dst_url:          Google Drive folder URL (destination)
        output_name:      Filename for the merged PDF
        credentials_file: Path to OAuth2 client credentials JSON
        token_file:       Path to stored token JSON (created/refreshed automatically)

    Returns:
        dict with keys: id, name, webViewLink
    """
    src_id = extract_folder_id(src_url)
    dst_id = extract_folder_id(dst_url)

    creds = authenticate(credentials_file, token_file)
    service = build("drive", "v3", credentials=creds)

    log.info("Listing files in source folder %s ...", src_id)
    files = list_files_in_folder(service, src_id)
    if not files:
        raise RuntimeError(f"No files found in source folder: {src_id}")

    log.info("Found %d file(s)", len(files))
    pdf_parts: list[bytes] = []
    for f in files:
        pdf_bytes = file_to_pdf_bytes(service, f)
        if pdf_bytes:
            pdf_parts.append(pdf_bytes)

    if not pdf_parts:
        raise RuntimeError("No convertible files found (all skipped).")

    log.info("Merging %d PDF(s)...", len(pdf_parts))
    merged = merge_pdfs(pdf_parts)

    log.info("Uploading merged PDF to destination folder %s ...", dst_id)
    result = upload_pdf(service, merged, output_name, dst_id)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert all files in a Google Drive folder to a single merged PDF."
    )
    parser.add_argument("--src", required=True, help="Source Drive folder URL or ID")
    parser.add_argument("--dst", required=True, help="Destination Drive folder URL or ID")
    parser.add_argument("--output", default="merged.pdf", help="Output PDF filename (default: merged.pdf)")
    parser.add_argument(
        "--credentials",
        default=os.environ.get("GDRIVE_CREDENTIALS_FILE", "credentials.json"),
        help="Path to OAuth2 credentials JSON (default: credentials.json)",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("GDRIVE_TOKEN_FILE", "token.json"),
        help="Path to token JSON (default: token.json)",
    )
    args = parser.parse_args()

    try:
        result = run(
            src_url=args.src,
            dst_url=args.dst,
            output_name=args.output,
            credentials_file=args.credentials,
            token_file=args.token,
        )
        print(result["webViewLink"])
        sys.exit(0)
    except Exception as e:
        log.error("%s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
