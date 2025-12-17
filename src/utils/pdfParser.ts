import * as pdfjsLib from 'pdfjs-dist';
import { Question } from '../store/questionStore';

// PDF.js worker 설정 - 로컬 환경 최적화
if (typeof window !== 'undefined') {
  pdfjsLib.GlobalWorkerOptions.workerSrc = '/pdfjs/pdf.worker.min.js';
} else {
  pdfjsLib.GlobalWorkerOptions.workerSrc = `https://unpkg.com/pdfjs-dist@${pdfjsLib.version}/build/pdf.worker.min.js`;
}

export interface ExtractedImage {
  pageNumber: number;
  imageIndex: number;
  dataUrl: string;
  width: number;
  height: number;
}

export interface ParsedPDFContent {
  text: string;
  pages: number;
  images?: ExtractedImage[];
}

const KOREAN_STOPWORDS = new Set([
  '다음',
  '무엇',
  '다음은',
  '다음의',
  '다음중',
  '다음중에서',
  '어느',
  '다음에서',
  '가장',
  '옳은',
  '있는',
  '것은',
  '옳지',
  '설명으로',
  '맞는',
  '맞는것은',
  '해당하는'
]);

const OPTION_SYMBOLS = ['①', '②', '③', '④'];

const symbolToIndex: Record<string, number> = {
  '①': 0,
  '②': 1,
  '③': 2,
  '④': 3
};

const normalizeText = (text: string) =>
  text
    .replace(/\r\n/g, '\n')
    .replace(/\r/g, '\n')
    .replace(/\u00a0/g, ' ')
    .replace(/\t/g, ' ');

const extractKeywords = (text: string, limit = 3) => {
  const words = text.match(/[가-힣A-Za-z]{2,}/g) || [];
  const unique: string[] = [];

  for (const word of words) {
    const normalized = word.toLowerCase();
    if (KOREAN_STOPWORDS.has(normalized)) continue;
    if (unique.some(existing => existing.toLowerCase() === normalized)) continue;
    unique.push(word.trim());
    if (unique.length >= limit) break;
  }

  return unique;
};

const estimateDifficulty = (question: string, options: string[]): Question['difficulty'] => {
  const lengthScore = question.length;
  const averageOptionLength = options.reduce((sum, option) => sum + option.length, 0) / options.length;

  if (lengthScore > 220 || averageOptionLength > 90) {
    return 'hard';
  }

  if (lengthScore > 120 || averageOptionLength > 65) {
    return 'medium';
  }

  return 'easy';
};

// 이미지 추출 함수
async function extractImagesFromPage(page: any, pageNum: number): Promise<ExtractedImage[]> {
  const images: ExtractedImage[] = [];

  try {
    const operatorList = await page.getOperatorList();
    const objs = page.objs;

    for (let i = 0; i < operatorList.fnArray.length; i++) {
      const fnId = operatorList.fnArray[i];

      // OPS.paintImageXObject = 85, OPS.paintJpegXObject = 82
      if (fnId === 85 || fnId === 82) {
        const imgName = operatorList.argsArray[i][0];

        try {
          const imgData = await new Promise<any>((resolve, reject) => {
            objs.get(imgName, (data: any) => {
              if (data) resolve(data);
              else reject(new Error('Image not found'));
            });
          });

          if (imgData && imgData.data) {
            const canvas = document.createElement('canvas');
            canvas.width = imgData.width;
            canvas.height = imgData.height;
            const ctx = canvas.getContext('2d');

            if (ctx) {
              const imageData = ctx.createImageData(imgData.width, imgData.height);
              const data = imgData.data;

              // Convert image data to RGBA format
              if (imgData.kind === 1) {
                // RGB format
                for (let j = 0, k = 0; j < data.length; j += 3, k += 4) {
                  imageData.data[k] = data[j];
                  imageData.data[k + 1] = data[j + 1];
                  imageData.data[k + 2] = data[j + 2];
                  imageData.data[k + 3] = 255;
                }
              } else if (imgData.kind === 2) {
                // RGBA format
                for (let j = 0; j < data.length; j++) {
                  imageData.data[j] = data[j];
                }
              } else {
                // Grayscale
                for (let j = 0, k = 0; j < data.length; j++, k += 4) {
                  imageData.data[k] = data[j];
                  imageData.data[k + 1] = data[j];
                  imageData.data[k + 2] = data[j];
                  imageData.data[k + 3] = 255;
                }
              }

              ctx.putImageData(imageData, 0, 0);

              const dataUrl = canvas.toDataURL('image/png');

              // Skip very small images (likely icons or decorations)
              if (imgData.width > 50 && imgData.height > 50) {
                images.push({
                  pageNumber: pageNum,
                  imageIndex: images.length,
                  dataUrl,
                  width: imgData.width,
                  height: imgData.height
                });
              }
            }
          }
        } catch (imgError) {
          console.warn(`페이지 ${pageNum}의 이미지 추출 실패:`, imgError);
        }
      }
    }
  } catch (error) {
    console.warn(`페이지 ${pageNum}의 이미지 리스트 추출 실패:`, error);
  }

  return images;
}

export async function extractTextFromPDF(file: File, extractImages: boolean = false): Promise<ParsedPDFContent> {
  try {
    const arrayBuffer = await file.arrayBuffer();
    const pdf = await pdfjsLib.getDocument({
      data: arrayBuffer,
      cMapUrl: '/pdfjs/cmaps/',
      cMapPacked: true,
      standardFontDataUrl: '/pdfjs/standard_fonts/'
    }).promise;

    let fullText = '';
    const allImages: ExtractedImage[] = [];

    for (let pageNum = 1; pageNum <= pdf.numPages; pageNum++) {
      const page = await pdf.getPage(pageNum);
      const textContent = await page.getTextContent();
      const pageText = textContent.items
        .map((item: any) => item.str)
        .join(' ');
      fullText += pageText + '\n';

      // Extract images if requested
      if (extractImages) {
        const pageImages = await extractImagesFromPage(page, pageNum);
        allImages.push(...pageImages);
      }
    }

    return {
      text: fullText,
      pages: pdf.numPages,
      images: extractImages ? allImages : undefined
    };
  } catch (error) {
    console.error('PDF 텍스트 추출 오류:', error);
    throw new Error(`PDF 파싱 실패: ${error.message}`);
  }
}

// 별도의 이미지 추출 함수 export
export async function extractImagesFromPDF(file: File): Promise<ExtractedImage[]> {
  try {
    const arrayBuffer = await file.arrayBuffer();
    const pdf = await pdfjsLib.getDocument({
      data: arrayBuffer,
      cMapUrl: '/pdfjs/cmaps/',
      cMapPacked: true,
      standardFontDataUrl: '/pdfjs/standard_fonts/'
    }).promise;

    const allImages: ExtractedImage[] = [];

    for (let pageNum = 1; pageNum <= pdf.numPages; pageNum++) {
      const page = await pdf.getPage(pageNum);
      const pageImages = await extractImagesFromPage(page, pageNum);
      allImages.push(...pageImages);
    }

    return allImages;
  } catch (error) {
    console.error('PDF 이미지 추출 오류:', error);
    throw new Error(`PDF 이미지 추출 실패: ${error.message}`);
  }
}

export function parseQuestionsWithHeuristics(
  pdfText: string,
  subject: string,
  examSession: string
): Question[] {
  const normalized = normalizeText(pdfText);
  const questionRegex = /(?:^|\n)(?:문제\s*)?(\d{1,3})\s*[).]\s*([\s\S]*?)(?=\n(?:문제\s*)?\d{1,3}\s*[).]\s*|$)/g;
  const questions: Question[] = [];
  let match: RegExpExecArray | null;
  const timestampBase = Date.now().toString(36);
  let fallbackCounter = 0;

  while ((match = questionRegex.exec(normalized)) !== null) {
    let body = match[2].trim();
    if (!body) continue;

    // Remove explanation and answers for cleaner parsing
    let explanation: string | undefined;
    const explanationMatch = body.match(/해설\s*[:：]?\s*([\s\S]*)/);
    if (explanationMatch) {
      explanation = explanationMatch[1].trim();
      body = body.replace(explanationMatch[0], '').trim();
    }

    let correctAnswer: number | undefined;
    const answerMatch = body.match(/(?:정답|답)\s*(?:\(|\[)?\s*[:：]?\s*([①②③④1-4])/);
    if (answerMatch) {
      const answerSymbol = answerMatch[1];
      correctAnswer = symbolToIndex[answerSymbol] ?? (parseInt(answerSymbol, 10) - 1);
      body = body.replace(answerMatch[0], '').trim();
    }

    const firstSymbolIndex = OPTION_SYMBOLS
      .map(symbol => body.indexOf(symbol))
      .filter(index => index >= 0)
      .sort((a, b) => a - b)[0];

    const numericOptionRegex = /(?:^|\n)\s*([1-4])\s*[).．ㆍ:]\s*/g;
    const numericMatches = [...body.matchAll(numericOptionRegex)];

    const firstNumericIndex = numericMatches.length >= 4
      ? numericMatches[0].index ?? -1
      : -1;

    const optionStartIndex =
      typeof firstSymbolIndex === 'number'
        ? firstSymbolIndex
        : firstNumericIndex;

    const rawQuestion = optionStartIndex >= 0 ? body.slice(0, optionStartIndex) : body;
    const questionText = rawQuestion.replace(/\s+/g, ' ').trim();

    let options: string[] = [];
    if (optionStartIndex >= 0) {
      const optionSection = body.slice(optionStartIndex);
      const symbolOptions = [...optionSection.matchAll(/[①②③④]\s*([\s\S]*?)(?=[①②③④]\s*|$)/g)]
        .map(optionMatch => optionMatch[1].replace(/\s+/g, ' ').trim())
        .filter(option => option.length > 0);

      if (symbolOptions.length >= 4) {
        options = symbolOptions.slice(0, 4);
      } else {
        const numericOptions = [...optionSection.matchAll(/(?:^|\n)\s*([1-4])\s*[).．ㆍ:]\s*([\s\S]*?)(?=(?:\n\s*[1-4]\s*[).．ㆍ:]|\n?\s*[①②③④]|$))/g)]
          .map(optionMatch => optionMatch[2].replace(/\s+/g, ' ').trim())
          .filter(option => option.length > 0);
        if (numericOptions.length >= 4) {
          options = numericOptions.slice(0, 4);
        }
      }
    }

    if (options.length < 4) {
      continue;
    }

    if (typeof correctAnswer !== 'number' || correctAnswer < 0 || correctAnswer > 3) {
      correctAnswer = 0;
      const defaultExplanation = '정답 정보를 찾을 수 없어 1번을 임시 정답으로 설정했습니다.';
      explanation = explanation ? `${explanation}\n${defaultExplanation}` : defaultExplanation;
    }

    const baseHashtags = [subject.trim(), examSession.trim()].filter(Boolean);
    const keywords = extractKeywords(questionText);
    const hashtags = Array.from(new Set([...baseHashtags, ...keywords]));

    const difficulty = estimateDifficulty(questionText, options);

    questions.push({
      id: `heuristic-${timestampBase}-${fallbackCounter++}`,
      question: questionText,
      options,
      correctAnswer,
      hashtags,
      difficulty,
      explanation
    });
  }

  return questions;
}

// MCP 클라이언트 구현
export async function parseQuestionsWithMCP(
  pdfText: string,
  subject: string,
  examSession: string,
  mcpEndpoint: string = 'http://localhost:11434'
): Promise<Question[]> {
  const prompt = `
다음은 한국어 기출문제 PDF에서 추출한 텍스트입니다. 이 텍스트를 분석하여 객관식 문제들을 찾아 JSON 형태로 구조화해주세요.

과목: ${subject}
회차: ${examSession}

추출할 정보:
1. 문제 번호와 문제 내용
2. 4개의 선택지 (①, ②, ③, ④ 또는 1, 2, 3, 4)
3. 정답 (0-3 인덱스)
4. 관련 키워드 해시태그
5. 난이도 추정 (easy, medium, hard)

응답 형식 (JSON 배열):
[
  {
    "question": "문제 내용",
    "options": ["선택지1", "선택지2", "선택지3", "선택지4"],
    "correctAnswer": 정답인덱스(0-3),
    "hashtags": ["${subject}", "${examSession}", "키워드1", "키워드2"],
    "difficulty": "easy|medium|hard",
    "explanation": "해설 (있는 경우)"
  }
]

PDF 텍스트:
${pdfText.substring(0, 8000)}

다음 조건을 만족하는 완전한 객관식 문제만 추출해주세요:
- 문제 내용이 명확히 구분되는 것
- 4개의 선택지가 모두 있는 것
- 한국어로 작성된 것
- 의미있는 문제인 것

JSON 배열만 응답해주세요.`;

  try {
    const response = await fetch(`${mcpEndpoint}/api/generate`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        model: 'eeve-korean-10.8b:latest', // 한국어 모델 사용
        prompt: prompt,
        stream: false,
        options: {
          temperature: 0.1,
          top_k: 40,
          top_p: 0.95,
        }
      }),
    });

    if (!response.ok) {
      throw new Error(`MCP 서버 오류: ${response.status} - ${response.statusText}`);
    }

    const data = await response.json();
    const content = data.response;
    
    // JSON 부분만 추출
    const jsonMatch = content.match(/\[[\s\S]*\]/);
    if (!jsonMatch) {
      throw new Error('AI 응답에서 JSON을 찾을 수 없습니다.');
    }

    const parsedQuestions = JSON.parse(jsonMatch[0]);
    
    // Question 타입에 맞게 변환하고 ID 추가
    return parsedQuestions.map((q: any) => ({
      id: Math.random().toString(36).substr(2, 9),
      question: q.question,
      options: q.options,
      correctAnswer: q.correctAnswer,
      hashtags: q.hashtags,
      difficulty: q.difficulty,
      explanation: q.explanation
    }));

  } catch (error) {
    console.error('MCP 파싱 오류:', error);
    throw new Error(`로컬 AI 모델 파싱 중 오류가 발생했습니다: ${error.message}`);
  }
}

// OpenAI 호환성을 위해 기존 함수명 유지하되 내부에서 Gemini 사용
export async function parseQuestionsWithGemini(
  pdfText: string, 
  subject: string, 
  examSession: string,
  apiKey: string
): Promise<Question[]> {
  const prompt = `
다음은 한국어 기출문제 PDF에서 추출한 텍스트입니다. 이 텍스트를 분석하여 객관식 문제들을 찾아 JSON 형태로 구조화해주세요.

과목: ${subject}
회차: ${examSession}

추출할 정보:
1. 문제 번호와 문제 내용
2. 4개의 선택지 (①, ②, ③, ④ 또는 1, 2, 3, 4)
3. 정답 (0-3 인덱스)
4. 관련 키워드 해시태그
5. 난이도 추정 (easy, medium, hard)

응답 형식 (JSON 배열):
[
  {
    "question": "문제 내용",
    "options": ["선택지1", "선택지2", "선택지3", "선택지4"],
    "correctAnswer": 정답인덱스(0-3),
    "hashtags": ["${subject}", "${examSession}", "키워드1", "키워드2"],
    "difficulty": "easy|medium|hard",
    "explanation": "해설 (있는 경우)"
  }
]

PDF 텍스트:
${pdfText.substring(0, 8000)} // 너무 긴 텍스트는 잘라서 전송

다음 조건을 만족하는 완전한 객관식 문제만 추출해주세요:
- 문제 내용이 명확히 구분되는 것
- 4개의 선택지가 모두 있는 것
- 한국어로 작성된 것
- 의미있는 문제인 것

JSON 배열만 응답해주세요.`;

  try {
    const response = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key=${apiKey}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        contents: [
          {
            parts: [
              {
                text: prompt
              }
            ]
          }
        ],
        generationConfig: {
          temperature: 0.1,
          topK: 40,
          topP: 0.95,
          maxOutputTokens: 4096,
        },
        safetySettings: [
          {
            category: "HARM_CATEGORY_HARASSMENT",
            threshold: "BLOCK_MEDIUM_AND_ABOVE"
          },
          {
            category: "HARM_CATEGORY_HATE_SPEECH",
            threshold: "BLOCK_MEDIUM_AND_ABOVE"
          },
          {
            category: "HARM_CATEGORY_SEXUALLY_EXPLICIT",
            threshold: "BLOCK_MEDIUM_AND_ABOVE"
          },
          {
            category: "HARM_CATEGORY_DANGEROUS_CONTENT",
            threshold: "BLOCK_MEDIUM_AND_ABOVE"
          }
        ]
      }),
    });

    if (!response.ok) {
      const errorData = await response.json();
      throw new Error(`Gemini API 오류: ${response.status} - ${errorData.error?.message || response.statusText}`);
    }

    const data = await response.json();
    
    if (!data.candidates || data.candidates.length === 0) {
      throw new Error('Gemini API에서 응답을 받지 못했습니다.');
    }

    const content = data.candidates[0].content.parts[0].text;
    
    // JSON 부분만 추출
    const jsonMatch = content.match(/\[[\s\S]*\]/);
    if (!jsonMatch) {
      throw new Error('AI 응답에서 JSON을 찾을 수 없습니다.');
    }

    const parsedQuestions = JSON.parse(jsonMatch[0]);
    
    // Question 타입에 맞게 변환하고 ID 추가
    return parsedQuestions.map((q: any) => ({
      id: Math.random().toString(36).substr(2, 9),
      question: q.question,
      options: q.options,
      correctAnswer: q.correctAnswer,
      hashtags: q.hashtags,
      difficulty: q.difficulty,
      explanation: q.explanation
    }));

  } catch (error) {
    console.error('Gemini 파싱 오류:', error);
    throw new Error(`문제 파싱 중 오류가 발생했습니다: ${error.message}`);
  }
}

// 통합 파싱 함수 - 로컬 우선, Gemini 대안
export async function parseQuestionsWithAI(
  pdfText: string, 
  subject: string, 
  examSession: string,
  apiKey: string,
  useLocalModel: boolean = true,
  mcpEndpoint: string = 'http://localhost:11434'
): Promise<Question[]> {
  if (useLocalModel) {
    try {
      return await parseQuestionsWithMCP(pdfText, subject, examSession, mcpEndpoint);
    } catch (error) {
      console.warn('로컬 모델 사용 실패, Gemini로 대체:', error);
      // 로컬 모델 실패시 Gemini로 대체
      return parseQuestionsWithGemini(pdfText, subject, examSession, apiKey);
    }
  } else {
    return parseQuestionsWithGemini(pdfText, subject, examSession, apiKey);
  }
}
