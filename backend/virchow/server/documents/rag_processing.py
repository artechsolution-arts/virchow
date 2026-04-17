import hashlib
import os
import shutil
import traceback
from typing import List, Optional
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy import select

from virchow.db.custom_rag_models import FileProgress, FileStage, PDFDoc, Chunk, Department, RagUser
from virchow.utils.logger import setup_logger

logger = setup_logger()

# Global parser instance (lazy loaded)
_PARSER = None

def get_parser():
    global _PARSER
    if _PARSER is None:
        try:
            from dots_ocr.parser import DotsOCRParser
            # Monkeypatch if needed, but for now we focus on the database
            logger.info("Initializing DotsOCRParser for background processing...")
            _PARSER = DotsOCRParser(use_hf=True)
        except ImportError:
            logger.warning("DotsOCR not installed. Falling back to dummy text extraction.")
            _PARSER = "dummy"
    return _PARSER

def process_rag_upload(db_session: Session, file_id: str):
    """Processes a single RAG upload record using the new FileProgress schema."""
    # Use SQLAlchemy select to find the record
    progress = db_session.execute(select(FileProgress).where(FileProgress.file_id == file_id)).scalars().first()
    
    if not progress:
        logger.error(f"File progress record {file_id} not found for processing.")
        return

    try:
        # 1. Start Validation
        progress.stage = FileStage.VALIDATING
        progress.pct = 10
        db_session.commit()

        file_path = progress.file_path
        filename = progress.filename

        # 2. OCR / Parsing
        progress.stage = FileStage.OCR
        progress.pct = 25
        db_session.commit()

        logger.info(f"Starting OCR for {filename}... (File ID: {file_id})")
        parser = get_parser()
        
        extracted_text = ""
        page_count = 0

        if parser == "dummy":
            extracted_text = f"Simulated extracted text for {filename}.\nThis is a placeholder since DotsOCR is missing."
            page_count = 1
        else:
            ocr_results = parser.parse_file(file_path)
            for res in ocr_results:
                page_count += 1
                md_path = res.get("md_content_path")
                if md_path and os.path.exists(md_path):
                    with open(md_path, "r", encoding="utf-8") as f:
                        extracted_text += f.read() + "\n\n"

        if not extracted_text.strip():
            raise Exception("No text could be extracted from the document.")

        # 3. Chunking
        progress.stage = FileStage.CHUNKING
        progress.pct = 45
        db_session.commit()

        # Create main PDFDoc record
        doc = PDFDoc(
            file_reference_id=progress.file_id,
            filename=filename,
            file_path=file_path,
            extracted_text=extracted_text,
            page_count=page_count,
            content_hash=hashlib.sha256(extracted_text.encode()).hexdigest()
        )
        db_session.add(doc)
        db_session.flush()

        # Simple Chunker
        chunk_size = 1000
        chunks = [extracted_text[i:i + chunk_size] for i in range(0, len(extracted_text), chunk_size)]
        
        for idx, chunk_text in enumerate(chunks):
            chunk = Chunk(
                doc_id=doc.doc_id,
                text=chunk_text,
                token_count=len(chunk_text.split()),
                chunk_index=idx,
                page_num=0
            )
            db_session.add(chunk)

        # 4. Success
        progress.stage = FileStage.DONE
        progress.pct = 100
        db_session.commit()
        logger.info(f"Successfully processed {filename}")

    except Exception as e:
        error_detail = f"{str(e)}"
        logger.error(f"Failed to process upload {file_id}: {error_detail}\n{traceback.format_exc()}")
        db_session.rollback()
        try:
            # Re-fetch fresh
            progress = db_session.execute(select(FileProgress).where(FileProgress.file_id == file_id)).scalars().first()
            if progress:
                progress.stage = FileStage.ERROR
                progress.pct = 0
                progress.error = error_detail
                db_session.commit()
        except Exception as db_err:
            logger.error(f"Failed to update error status: {db_err}")
