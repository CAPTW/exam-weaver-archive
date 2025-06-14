
import { create } from 'zustand';

export interface Question {
  id: string;
  question: string;
  options: string[];
  correctAnswer: number;
  hashtags: string[];
  difficulty: 'easy' | 'medium' | 'hard';
  explanation?: string;
  imageUrl?: string;
}

interface QuestionStore {
  questions: Question[];
  addQuestions: (questions: Question[]) => void;
  deleteQuestion: (id: string) => void;
  updateQuestion: (id: string, updates: Partial<Question>) => void;
  getQuestionsBySubject: () => Map<string, number>;
  getTotalQuestions: () => number;
}

export const useQuestionStore = create<QuestionStore>((set, get) => ({
  questions: [],
  
  addQuestions: (newQuestions) => set((state) => ({
    questions: [...state.questions, ...newQuestions]
  })),
  
  deleteQuestion: (id) => set((state) => ({
    questions: state.questions.filter(q => q.id !== id)
  })),
  
  updateQuestion: (id, updates) => set((state) => ({
    questions: state.questions.map(q => 
      q.id === id ? { ...q, ...updates } : q
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
  
  getTotalQuestions: () => get().questions.length
}));
