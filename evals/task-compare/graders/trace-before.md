---
type: regex
pattern: '^(?=[\s\S]*?19880 B -> 9110 B \(10770 (?:bytes smaller|바이트 감소)\))(?=[\s\S]*?Dockerfile:3 COPY requirements\.txt: ok -> (?:EXCLUDED|제외됨))(?=[\s\S]*?: 16(?: files?|개), 19880 B \((?:not sent|보내지 않음): 3(?: files?|개), 1422 B\))(?=[\s\S]*?(?<![\w/.-])app +8783 B +6(?: files?|개))(?=[\s\S]*?Dockerfile:3 COPY requirements\.txt +ok)(?=[\s\S]*?Dockerfile:4 COPY app +ok)(?=[\s\S]*?Dockerfile:5 COPY assets/fonts +ok)(?=[\s\S]*?Dockerfile\.dockerignore:1 ''\*\.csv'' \[root-anchored\])(?=[\s\S]*?(?:Result: no COPY/ADD problem and no secret-looking file\.|결과: COPY/ADD 문제도, 비밀처럼 보이는 파일도 없음\.))(?=[\s\S]*?(?<![\w/.-])assets +6348 B +3(?: files?|개))[\s\S]*?Dockerfile\.dockerignore:2 ''third_party'' \[root-anchored\]'
target: trace
---
