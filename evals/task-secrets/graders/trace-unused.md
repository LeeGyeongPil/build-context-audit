---
type: regex
pattern: '^(?=[\s\S]*?(?:secret-looking files sent to the builder: 4|비밀처럼 보이는 파일 4개가 빌더로 전송됨))(?=[\s\S]*?certs/server\.pem +\(private-key\))(?![\s\S]*?certs/tls\.key +\(private-key\))(?=[\s\S]*?deploy/id_rsa +\(ssh-key\))(?=[\s\S]*?infra/terraform\.tfstate +\(terraform-state\))(?=[\s\S]*?kubeconfig +\(kubeconfig\))(?=[\s\S]*?: 9(?: files?|개), 485 B \((?:not sent|보내지 않음): 5(?: files?|개), 71 B\))(?=[\s\S]*?(?<![\w/.-])\. +214 B +3(?: files?|개))(?=[\s\S]*?Dockerfile:3 COPY \. +ok)(?=[\s\S]*?Dockerfile\.dockerignore:7 ''kubeconfig  # cluster access'' \[inline-comment\])(?=[\s\S]*?(?:Result: COPY/ADD problems: 0, secret-looking files: 4\.|결과: COPY/ADD 문제 0개, 비밀처럼 보이는 파일 4개\.))(?=[\s\S]*?Dockerfile\.dockerignore:5 ''secrets'' \[unused-rule\])[\s\S]*?Dockerfile\.dockerignore:10 ''!certs'' \[unused-rule\]'
target: trace
---
