---
type: regex
pattern: '^(?=[\s\S]*?release: (?:EXCLUDED|제외됨)[^\n]{1,30}?Dockerfile\.dockerignore:4 ''release'')(?=[\s\S]*?docs/api/openapi\.yaml: (?:INCLUDED|포함됨)[^\n]{1,30}?Dockerfile\.dockerignore:3 ''!docs/api/openapi\.yaml'')(?=[\s\S]*?config/app\.yaml: (?:EXCLUDED|제외됨)[^\n]{1,30}?Dockerfile\.dockerignore:8 ''config'')(?=[\s\S]*?: 6(?: files?|개), 1451 B \((?:not sent|보내지 않음): 5(?: files?|개), 789 B\))(?=[\s\S]*?(?<![\w/.-])docs +640 B +1(?: files?|개))(?=[\s\S]*?Dockerfile:3 COPY \. +ok)(?=[\s\S]*?Dockerfile\.dockerignore:5 ''\*\.bak  # editor backups'' \[inline-comment\])(?=[\s\S]*?(?:Result: no COPY/ADD problem and no secret-looking file\.|결과: COPY/ADD 문제도, 비밀처럼 보이는 파일도 없음\.))[\s\S]*?notes\.bak: (?:INCLUDED|포함됨)[^\n]{1,6}(?:no line matches|맞는 줄 없음)'
target: trace
---
