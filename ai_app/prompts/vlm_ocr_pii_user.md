Please process the attached document image(s).

1. Extract ALL text from the image exactly as written.
2. Identify all PII (personally identifiable information) entities in the extracted text.

Return a JSON object in this exact format:
```json
{{
    "ocr_text": "The complete extracted text from the image...",
    "pii_entities": [
        {{"text": "홍길동", "type": "NAME"}},
        {{"text": "010-1234-5678", "type": "PHONE"}},
        {{"text": "hong@example.com", "type": "EMAIL"}},
        {{"text": "900101-1234567", "type": "RRN"}},
        {{"text": "서울특별시 강남구 테헤란로 123", "type": "ADDRESS"}}
    ]
}}
```

Rules:
- "ocr_text": Complete text extracted from the image in reading order
- "pii_entities": Array of detected PII items. Each has "text" (exact string from ocr_text) and "type" (NAME, PHONE, EMAIL, RRN, or ADDRESS)
- If no PII is found, return an empty array for "pii_entities"
- The "text" field in each entity MUST be an exact substring of "ocr_text"
