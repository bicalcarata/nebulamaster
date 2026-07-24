from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    ListFlowable,
    ListItem,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)

ROOT_DIR = Path(__file__).resolve().parents[1]
OUTPUT_PATH = ROOT_DIR / "docs" / "nebula-master-get-started.pdf"


def _paragraphs(styles: dict[str, ParagraphStyle]) -> list[object]:
    body = styles["BodyText"]
    heading = styles["Heading2"]
    title = styles["Title"]
    note = styles["NebulaNote"]

    def bullet_items(items: list[str]) -> ListFlowable:
        return ListFlowable(
            [
                ListItem(Paragraph(item, body), leftIndent=0)
                for item in items
            ],
            bulletType="bullet",
            leftIndent=14,
            bulletFontName="Helvetica",
            bulletFontSize=10,
            bulletOffsetY=1,
        )

    story: list[object] = [
        Paragraph("Nebula Master - Get Started", title),
        Spacer(1, 6 * mm),
        Paragraph(
            "This guide is for someone opening Nebula Master for the first time "
            "after installing it. It follows the real first-use flow: open an "
            "image, choose where to save the project, add a few adjustments, "
            "save the project, export an image, and reopen the project later.",
            body,
        ),
        Spacer(1, 5 * mm),
        Paragraph("1. What Nebula Master Is", heading),
        Paragraph(
            "Nebula Master is a non-destructive image mastering tool. Your source image "
            "stays unchanged. The project stores adjustment instructions, and the app "
            "renders previews and exports from those instructions.",
            body,
        ),
        Spacer(1, 4 * mm),
        Paragraph("2. First Launch", heading),
        bullet_items(
            [
                "Open Nebula Master.",
                "If Windows or macOS shows a security prompt, allow the app to run "
                "if you trust the download source.",
                "When you first start, you may have no projects yet. That is normal.",
                "Wait for the main window to appear fully before creating or opening a project.",
            ]
        ),
        Spacer(1, 4 * mm),
        Paragraph("3. Start a New Project From an Image", heading),
        bullet_items(
            [
                "Choose File > New Project from Image.",
                "Pick a source image. TIFF is the best place to start, but PNG and "
                "JPEG are also supported.",
                "After choosing the image, Nebula Master will immediately ask where "
                "the new project folder should be created.",
                "Choose the parent location where you want the project to live.",
                "The app then creates a new project folder for that image.",
                "Nebula Master will make a project directory and copy the source "
                "image into it as an immutable input.",
            ]
        ),
        Paragraph(
            "This second folder dialog is not asking where to save an export. It is "
            "asking where to create the Nebula Master project itself.",
            body,
        ),
        Spacer(1, 4 * mm),
        Paragraph("4. What the App Created", heading),
        bullet_items(
            [
                "A Nebula Master project folder is created on disk.",
                "That folder contains the project metadata and the imported source image.",
                "From this point on, you reopen the project folder, not the original image file.",
            ]
        ),
        Paragraph(
            "Think of the source image as the raw input and the project folder as the "
            "thing you keep working on over time.",
            body,
        ),
        Spacer(1, 4 * mm),
        Paragraph("5. Learn the Main Areas of the Window", heading),
        bullet_items(
            [
                "Left panel: project details, source list, adjustments, and regions.",
                "Center panel: image preview, zoom controls, preview/source "
                "toggle, and selection tools.",
                "Right panel: controls for the currently selected adjustment or region.",
                "Bottom panel: unsaved semantic changes that explain what you changed.",
            ]
        ),
        Spacer(1, 4 * mm),
        Paragraph("6. Add a First Adjustment", heading),
        bullet_items(
            [
                "Click Add in the Adjustments panel.",
                "Choose something simple like Brightness, Saturation, Blue, Red, or Black Point.",
                "Click the new adjustment in the list to edit its controls on the right.",
            ]
        ),
        Paragraph(
            "Adjustments are applied in order from top to bottom. You can move "
            "them earlier or later to change the final result.",
            body,
        ),
        Spacer(1, 4 * mm),
        Paragraph("7. Change Adjustment Settings", heading),
        bullet_items(
            [
                "Click an adjustment in the list to select it.",
                "The right-hand panel shows that adjustment's settings.",
                "Change the amount, target, colour point, black point, levels, "
                "or other controls depending on the adjustment type.",
                "The preview updates to show the current result.",
            ]
        ),
        Paragraph(
            "The right-hand panel always edits the currently selected adjustment. "
            "If you click a different adjustment in the list, the controls change to "
            "match that adjustment.",
            body,
        ),
        Spacer(1, 4 * mm),
        Paragraph("8. Target What the Adjustment Affects", heading),
        bullet_items(
            [
                "Use the Affects control to apply an adjustment to Nebula, Stars, "
                "or the Combined Image.",
                "Use colour adjustments when you want to change a specific colour family.",
                "Use Brightness, Saturation, Levels, or Black Point when you want "
                "broader tonal changes.",
            ]
        ),
        Spacer(1, 4 * mm),
        Paragraph("9. Pick a Colour Point From the Image", heading),
        bullet_items(
            [
                "For a colour-based adjustment, click Pick Colour Point.",
                "Then click a visible feature in the image preview.",
                "That sampled point becomes the midpoint for that colour family, "
                "so the adjustment mainly affects similar colours.",
            ]
        ),
        Paragraph(
            "If you are not sure where to click, start by sampling the exact "
            "nebula glow you want to strengthen or soften.",
            body,
        ),
        Spacer(1, 4 * mm),
        Paragraph("10. Create an Adjustment Directly From the Image", heading),
        bullet_items(
            [
                "Click Create Adjustment from Selection.",
                "Click a visible feature in the preview.",
                "Choose the adjustment type when prompted.",
                "Nebula Master will append a new declarative adjustment and render a new preview.",
            ]
        ),
        Spacer(1, 4 * mm),
        Paragraph("11. Use Regions When You Need Spatial Control", heading),
        bullet_items(
            [
                "Click Add Region to draw a polygon over part of the image.",
                "Use region edge softness to feather the boundary.",
                "Assign that region to an adjustment if you want the effect "
                "limited to part of the image.",
            ]
        ),
        Spacer(1, 4 * mm),
        Paragraph("12. Preview and Compare", heading),
        bullet_items(
            [
                "Use Show Preview to see the mastered image.",
                "Use Show Source to compare against the original source state.",
                "Use Before / After and Hold Previous when comparing changes.",
                "Use the overlay selector if you want to inspect the current star or nebula split.",
            ]
        ),
        Spacer(1, 4 * mm),
        Paragraph("13. Save the Project", heading),
        bullet_items(
            [
                "Nebula Master tracks unsaved semantic changes at the bottom of the window.",
                "Use Keep Change to keep the current working changes.",
                "Use Remove Selected Change or Revert All if you want to undo working edits.",
                "Save the project so the adjustment metadata is written to the project folder.",
            ]
        ),
        Paragraph(
            "Saving the project does not overwrite the original source image. The "
            "project folder is the real source of truth. Previews and generated "
            "renders can be recreated later.",
            body,
        ),
        Spacer(1, 4 * mm),
        Paragraph("14. Export an Image", heading),
        bullet_items(
            [
                "Use File > Export for Screen for PNG, JPEG, or TIFF screen output.",
                "Use File > Export for Print for print-oriented sizing and DPI.",
                "If you upscale, prefer Preserve Pixels when you want more output "
                "pixels without inventing detail.",
            ]
        ),
        Spacer(1, 4 * mm),
        Paragraph("15. Reopen the Project Later", heading),
        bullet_items(
            [
                "When you come back later, use File > Open Project.",
                "Select the Nebula Master project folder you created earlier.",
                "Do not start again from the original source image unless you "
                "want a brand-new project.",
            ]
        ),
        Paragraph(
            "A common beginner mistake is reopening the source TIFF, PNG, or JPEG "
            "instead of reopening the project folder. If you do that, Nebula Master "
            "will start creating a new project instead of continuing the old one.",
            body,
        ),
        Spacer(1, 4 * mm),
        Paragraph("16. Good First Workflow", heading),
        bullet_items(
            [
                "Start with a TIFF source if possible.",
                "Create a project from that image.",
                "Add one or two broad adjustments first: Black Point, Brightness, or Levels.",
                "Then add colour adjustments like Red, Blue, Cyan, Green, or Yellow.",
                "Use regions only after you know which area needs isolation.",
                "Save the project.",
                "Export a screen render and review it outside the app.",
                "Later, reopen the project folder and continue refining it.",
            ]
        ),
        Spacer(1, 4 * mm),
        Paragraph("17. If Something Looks Wrong", heading),
        bullet_items(
            [
                "If the whole image changes unexpectedly, recheck the selected "
                "colour point and the adjustment target.",
                "If a change is too broad, narrow it with a better colour point, "
                "region, or target selection.",
                "If preview rendering seems stuck, wait briefly, then restart "
                "the app and reopen the project.",
            ]
        ),
        Spacer(1, 4 * mm),
        Paragraph(
            "Tip: beginners usually get better results by making small changes "
            "with several adjustments rather than one aggressive adjustment.",
            note,
        ),
    ]
    return story


def build_pdf(output_path: Path) -> Path:
    styles = getSampleStyleSheet()
    styles["Title"].fontName = "Helvetica-Bold"
    styles["Title"].fontSize = 22
    styles["Title"].leading = 26
    styles["Title"].textColor = colors.HexColor("#14213D")
    styles["Heading2"].fontName = "Helvetica-Bold"
    styles["Heading2"].fontSize = 13
    styles["Heading2"].leading = 17
    styles["Heading2"].textColor = colors.HexColor("#1F3C88")
    styles["BodyText"].fontName = "Helvetica"
    styles["BodyText"].fontSize = 10
    styles["BodyText"].leading = 14
    styles["BodyText"].alignment = TA_LEFT
    styles.add(
        ParagraphStyle(
            name="NebulaNote",
            parent=styles["BodyText"],
            textColor=colors.HexColor("#7A3E00"),
            backColor=colors.HexColor("#F7F1E3"),
            borderPadding=6,
        )
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title="Nebula Master - Get Started",
        author="OpenAI Codex",
        subject="Basic getting started guide for Nebula Master users",
    )
    doc.build(_paragraphs(styles))
    return output_path


if __name__ == "__main__":
    build_pdf(OUTPUT_PATH)
    print(OUTPUT_PATH)
