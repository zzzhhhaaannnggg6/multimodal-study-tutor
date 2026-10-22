"""Small synthetic, redistribution-cleared PDFs with independent page markers."""


def visual_pdf(count=12, *, text=True, rotate_page=None, crop_page=None, huge_page=None, page_text=None) -> bytes:
    objects = []
    kids = " ".join(f"{4 + 2 * index} 0 R" for index in range(count))
    objects.extend([b"<< /Type /Catalog /Pages 2 0 R >>", f"<< /Type /Pages /Kids [{kids}] /Count {count} >>".encode(),
                    b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"])
    for number in range(1, count + 1):
        page_id = 4 + 2 * (number - 1)
        box = "0 0 100000 100000" if number == huge_page else "0 0 300 200"
        rotate = " /Rotate 90" if number == rotate_page else ""
        crop = " /CropBox [20 20 280 180]" if number == crop_page else ""
        page = f"<< /Type /Page /Parent 2 0 R /MediaBox [{box}]{rotate}{crop} /Resources << /Font << /F1 3 0 R >> >> /Contents {page_id + 1} 0 R >>"
        red, green, blue = ((1, 0, 0) if number % 2 else (0, 0, 1))
        content = f"{red} {green} {blue} rg 30 30 240 100 re f\n0 0 0 RG 40 40 m 260 120 l S\n"
        if text:
            message = page_text if page_text is not None else f"Synthetic page {number:02d}: E = m c2"
            message = message.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            content += f"0 0 0 rg BT /F1 14 Tf 30 160 Td ({message}) Tj ET\n"
        stream = content.encode()
        objects.extend([page.encode(), b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"endstream"])
    result = b"%PDF-1.4\n"
    offsets = []
    for number, obj in enumerate(objects, 1):
        offsets.append(len(result))
        result += f"{number} 0 obj\n".encode() + obj + b"\nendobj\n"
    start = len(result)
    result += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    result += b"".join(f"{offset:010} 00000 n \n".encode() for offset in offsets)
    return result + f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode()
