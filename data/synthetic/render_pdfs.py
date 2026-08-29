"""
Renders the buyer RFP and all synthetic supplier proposals to PDF using
reportlab. Run directly: python3 data/synthetic/render_pdfs.py
"""
import os
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak

from content import BUYER_RFP, ALL_SUPPLIERS

OUT_DIR = os.path.dirname(__file__)

styles = getSampleStyleSheet()
title_style = ParagraphStyle("TitleX", parent=styles["Title"], fontSize=20, spaceAfter=6)
subtitle_style = ParagraphStyle("SubtitleX", parent=styles["Normal"], fontSize=12,
                                 textColor=colors.HexColor("#1F3864"), spaceAfter=18)
heading_style = ParagraphStyle("HeadingX", parent=styles["Heading2"], fontSize=13,
                                textColor=colors.HexColor("#1F3864"), spaceBefore=14, spaceAfter=6)
body_style = ParagraphStyle("BodyX", parent=styles["Normal"], fontSize=11, leading=17,
                             spaceAfter=14)
note_style = ParagraphStyle("NoteX", parent=styles["Normal"], fontSize=8.5, leading=11,
                             textColor=colors.grey, spaceAfter=10)


def build_pdf(filename, title, subtitle, note, sections):
    path = os.path.join(OUT_DIR, filename)
    doc = SimpleDocTemplate(path, pagesize=LETTER,
                             topMargin=0.9 * inch, bottomMargin=0.8 * inch,
                             leftMargin=0.9 * inch, rightMargin=0.9 * inch)
    story = [Paragraph(title, title_style), Paragraph(subtitle, subtitle_style)]
    if note:
        story.append(Paragraph(note, note_style))
    story.append(Spacer(1, 6))
    for heading, text in sections:
        story.append(Paragraph(heading, heading_style))
        # reportlab Paragraph needs literal newlines converted to <br/>
        text_html = text.replace("\n\n", "<br/><br/>")
        story.append(Paragraph(text_html, body_style))
    doc.build(story)
    print(f"Wrote {path}")


def main():
    build_pdf(
        "Buyer_RFP_Meridian_Energy_Services.pdf",
        BUYER_RFP["title"],
        BUYER_RFP["subtitle"],
        "Synthetic procurement request authored for the Agentic RFP Evaluation mini project. "
        "No real confidential supplier or client data is used anywhere in this document set.",
        BUYER_RFP["sections"],
    )
    for supplier in ALL_SUPPLIERS:
        safe_name = supplier["supplier_name"].replace(" ", "_").replace(".", "")
        build_pdf(
            f"Supplier_{safe_name}.pdf",
            f"Response to RFP: {supplier['supplier_name']}",
            "AI-Assisted Tier 2/3 Application Management & Service Desk Platform",
            None,  # profile_note is authoring metadata, not part of the in-document text
            supplier["sections"],
        )


if __name__ == "__main__":
    main()
