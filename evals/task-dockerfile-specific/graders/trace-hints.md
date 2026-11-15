---
type: regex
pattern: '^(?=[\s\S]*?(?:ignore file|무시 파일): docker/api\.Dockerfile\.dockerignore)(?=[\s\S]*?: 5(?: files?|개), 8750 B \((?:not sent|보내지 않음): 10(?: files?|개), 4387 B\))(?=[\s\S]*?docker/api\.Dockerfile:6 COPY proto +(?:EXCLUDED|제외됨))(?=[\s\S]*?(?:decided by|결정 줄) docker/api\.Dockerfile\.dockerignore:2 ''\*'')(?=[\s\S]*?(?<![\w/.-])services +7186 B +3(?: files?|개))(?=[\s\S]*?docker/api\.Dockerfile:3 COPY go\.mod +ok)(?=[\s\S]*?docker/api\.Dockerfile:5 COPY services/api +ok)(?=[\s\S]*?docker/api\.Dockerfile\.dockerignore:8 ''services/api/testdata  # golden files, too big'' \[inline-comment\])(?=[\s\S]*?(?:Result: COPY/ADD problems: 1, secret-looking files: 0\.|결과: COPY/ADD 문제 1개, 비밀처럼 보이는 파일 0개\.))[\s\S]*?docker/api\.Dockerfile\.dockerignore:7 ''!\*\.proto'' \[unused-rule\]'
target: trace
---
