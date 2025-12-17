
import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export interface Question {
  id: string;
  question: string;
  options: string[];
  correctAnswer: number;
  hashtags: string[];
  difficulty: 'easy' | 'medium' | 'hard';
  explanation?: string;
  imageUrl?: string;
  imageData?: string; // Base64 encoded image data
  createdAt?: number;
  updatedAt?: number;
}

interface QuestionStore {
  questions: Question[];
  addQuestions: (questions: Question[]) => void;
  addQuestion: (question: Omit<Question, 'id' | 'createdAt' | 'updatedAt'>) => void;
  deleteQuestion: (id: string) => void;
  updateQuestion: (id: string, updates: Partial<Question>) => void;
  getQuestionsBySubject: () => Map<string, number>;
  getTotalQuestions: () => number;
  clearAllQuestions: () => void;
  exportQuestions: () => string;
  importQuestions: (jsonData: string) => boolean;
}

const generateId = () => `q-${Date.now().toString(36)}-${Math.random().toString(36).substr(2, 9)}`;

export const useQuestionStore = create<QuestionStore>()(
  persist(
    (set, get) => ({
      questions: [],

      addQuestions: (newQuestions) => set((state) => {
        const timestamp = Date.now();
        const questionsWithMeta = newQuestions.map(q => ({
          ...q,
          createdAt: q.createdAt || timestamp,
          updatedAt: timestamp
        }));
        return {
          questions: [...state.questions, ...questionsWithMeta]
        };
      }),

      addQuestion: (questionData) => set((state) => {
        const timestamp = Date.now();
        const newQuestion: Question = {
          ...questionData,
          id: generateId(),
          createdAt: timestamp,
          updatedAt: timestamp
        };
        return {
          questions: [...state.questions, newQuestion]
        };
      }),

      deleteQuestion: (id) => set((state) => ({
        questions: state.questions.filter(q => q.id !== id)
      })),

      updateQuestion: (id, updates) => set((state) => ({
        questions: state.questions.map(q =>
          q.id === id ? { ...q, ...updates, updatedAt: Date.now() } : q
        )
      })),

      getQuestionsBySubject: () => {
        const questions = get().questions;
        const subjectCount = new Map<string, number>();

        questions.forEach(question => {
          question.hashtags.forEach(tag => {
            subjectCount.set(tag, (subjectCount.get(tag) || 0) + 1);
          });
        });

        return subjectCount;
      },

      getTotalQuestions: () => get().questions.length,

      clearAllQuestions: () => set({ questions: [] }),

      exportQuestions: () => {
        const questions = get().questions;
        return JSON.stringify(questions, null, 2);
      },

      importQuestions: (jsonData: string) => {
        try {
          const imported = JSON.parse(jsonData);
          if (!Array.isArray(imported)) {
            return false;
          }
          const timestamp = Date.now();
          const validQuestions = imported.filter(q =>
            q.question &&
            Array.isArray(q.options) &&
            q.options.length >= 4 &&
            typeof q.correctAnswer === 'number'
          ).map(q => ({
            ...q,
            id: q.id || generateId(),
            hashtags: q.hashtags || [],
            difficulty: q.difficulty || 'medium',
            createdAt: q.createdAt || timestamp,
            updatedAt: timestamp
          }));

          set((state) => ({
            questions: [...state.questions, ...validQuestions]
          }));
          return true;
        } catch {
          return false;
        }
      }
    }),
    {
      name: 'exam-weaver-questions',
      version: 1,
    }
  )
);
