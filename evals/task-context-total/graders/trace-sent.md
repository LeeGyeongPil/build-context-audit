---
type: regex
pattern: '^(?=[\s\S]*?: 7(?: files?|개), 7665 B \((?:not sent|보내지 않음): 14(?: files?|개), 14976 B\))(?=[\s\S]*?(?<![\w/.-])src +4652 B +5(?: files?|개))(?=[\s\S]*?Dockerfile:3 COPY \. +ok)(?=[\s\S]*?Dockerfile\.dockerignore:7 ''\[!R\]\*\.md'' \[bang-class\])[\s\S]*?(?:Result: no COPY/ADD problem and no secret-looking file\.|결과: COPY/ADD 문제도, 비밀처럼 보이는 파일도 없음\.)'
target: trace
---
