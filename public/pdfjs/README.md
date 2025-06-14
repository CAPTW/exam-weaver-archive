
# PDF.js Files

이 폴더에는 PDF.js worker 파일들이 들어갑니다.

로컬 환경에서 사용하려면 다음 파일들을 복사해주세요:

```
public/pdfjs/
├── pdf.worker.min.js
├── cmaps/
└── standard_fonts/
```

다운로드 링크:
- https://unpkg.com/pdfjs-dist@5.3.31/build/pdf.worker.min.js
- https://unpkg.com/pdfjs-dist@5.3.31/cmaps/
- https://unpkg.com/pdfjs-dist@5.3.31/standard_fonts/

또는 npm install 후:
```bash
cp node_modules/pdfjs-dist/build/pdf.worker.min.js public/pdfjs/
cp -r node_modules/pdfjs-dist/cmaps public/pdfjs/
cp -r node_modules/pdfjs-dist/standard_fonts public/pdfjs/
```
