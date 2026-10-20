"""Public business intake, independent of demo codes, tutoring, and enrollment."""
import logging

from fastapi import APIRouter, HTTPException

from models.inquiries import InquiryRequest
from services.inquiry_service import inquiry_configured, send_inquiry

router = APIRouter(prefix="/inquiries", tags=["inquiries"])
log = logging.getLogger(__name__)


@router.post("")
async def submit_inquiry(req: InquiryRequest):
    if req.website:
        raise HTTPException(status_code=400, detail="Please leave the website field empty.")
    if not inquiry_configured(req.audience):
        raise HTTPException(status_code=503, detail="Inquiry email is temporarily unavailable.")
    sent = await send_inquiry(req)
    # Never log names, addresses, organization names, counts, or free text.
    log.info("Inquiry email: audience=%s accepted=%s", req.audience, sent)
    if not sent:
        raise HTTPException(status_code=502, detail="Your inquiry could not be sent. Please retry.")
    # Provider acceptance is not a claim about downstream inbox delivery.
    return {"sent": True}
