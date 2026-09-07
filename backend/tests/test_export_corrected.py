import zipfile
from io import BytesIO


def test_export_corrected_tracked_docx(client, auth_header):
    client.get("/api/v1/auth/me", headers=auth_header)
    res = client.post(
        "/api/v1/legal-tools/export-corrected",
        headers=auth_header,
        json={
            "documentText": "The term is one year.",
            "acceptedRedlines": [
                {
                    "clauseName": "Term",
                    "currentLanguage": "one year",
                    "replacementLanguage": "two years",
                }
            ],
            "contractType": "nda",
            "trackedChanges": True,
        },
    )
    assert res.status_code == 200
    assert "wordprocessingml.document" in res.headers["content-type"]
    data = res.content
    with zipfile.ZipFile(BytesIO(data)) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    assert "two years" in xml
    assert "w:ins" in xml or "w:del" in xml


def test_export_corrected_unauthenticated(client):
    res = client.post(
        "/api/v1/legal-tools/export-corrected",
        json={"documentText": "x", "acceptedRedlines": [], "trackedChanges": False},
    )
    assert res.status_code == 401


def test_export_corrected_too_large(client, auth_header):
    client.get("/api/v1/auth/me", headers=auth_header)
    res = client.post(
        "/api/v1/legal-tools/export-corrected",
        headers=auth_header,
        json={"documentText": "x" * 200_001, "acceptedRedlines": [], "trackedChanges": False},
    )
    assert res.status_code == 413
    assert res.json()["detail"]["error_code"] == "document_too_large"
