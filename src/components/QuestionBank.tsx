
import React, { useState } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Search, Filter, Edit, Trash2, Eye } from 'lucide-react';
import { useQuestionStore } from '../store/questionStore';
import QuestionDetail from './QuestionDetail';

const QuestionBank = () => {
  const { questions, deleteQuestion } = useQuestionStore();
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedSubject, setSelectedSubject] = useState('');
  const [selectedDifficulty, setSelectedDifficulty] = useState('');
  const [selectedQuestion, setSelectedQuestion] = useState(null);

  const filteredQuestions = questions.filter(question => {
    const matchesSearch = question.question.toLowerCase().includes(searchTerm.toLowerCase()) ||
                         question.hashtags.some(tag => tag.toLowerCase().includes(searchTerm.toLowerCase()));
    const matchesSubject = !selectedSubject || question.hashtags.includes(selectedSubject);
    const matchesDifficulty = !selectedDifficulty || question.difficulty === selectedDifficulty;
    
    return matchesSearch && matchesSubject && matchesDifficulty;
  });

  const allSubjects = Array.from(new Set(questions.flatMap(q => q.hashtags)));
  const difficulties = ['easy', 'medium', 'hard'];

  const getDifficultyColor = (difficulty: string) => {
    switch (difficulty) {
      case 'easy': return 'bg-green-100 text-green-800';
      case 'medium': return 'bg-yellow-100 text-yellow-800';
      case 'hard': return 'bg-red-100 text-red-800';
      default: return 'bg-gray-100 text-gray-800';
    }
  };

  const getDifficultyLabel = (difficulty: string) => {
    switch (difficulty) {
      case 'easy': return '쉬움';
      case 'medium': return '보통';
      case 'hard': return '어려움';
      default: return difficulty;
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-gray-900 mb-2">문제은행</h2>
        <p className="text-gray-600">저장된 문제들을 검색하고 관리하세요.</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center space-x-2">
            <Filter className="w-5 h-5" />
            <span>필터 및 검색</span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400 w-4 h-4" />
              <Input
                placeholder="문제 또는 해시태그 검색..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="pl-10"
              />
            </div>
            <Select value={selectedSubject} onValueChange={setSelectedSubject}>
              <SelectTrigger>
                <SelectValue placeholder="과목 선택" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="">모든 과목</SelectItem>
                {allSubjects.map(subject => (
                  <SelectItem key={subject} value={subject}>{subject}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={selectedDifficulty} onValueChange={setSelectedDifficulty}>
              <SelectTrigger>
                <SelectValue placeholder="난이도 선택" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="">모든 난이도</SelectItem>
                {difficulties.map(difficulty => (
                  <SelectItem key={difficulty} value={difficulty}>
                    {getDifficultyLabel(difficulty)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button 
              variant="outline" 
              onClick={() => {
                setSearchTerm('');
                setSelectedSubject('');
                setSelectedDifficulty('');
              }}
            >
              필터 초기화
            </Button>
          </div>
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 gap-4">
        {filteredQuestions.map((question, index) => (
          <Card key={question.id} className="hover:shadow-md transition-shadow duration-200">
            <CardContent className="p-6">
              <div className="flex justify-between items-start mb-4">
                <div className="flex-1">
                  <h3 className="text-lg font-medium text-gray-900 mb-2">
                    문제 {index + 1}: {question.question}
                  </h3>
                  <div className="flex flex-wrap gap-2 mb-3">
                    {question.hashtags.map((tag, tagIndex) => (
                      <Badge key={tagIndex} variant="secondary" className="text-xs">
                        {tag}
                      </Badge>
                    ))}
                    <Badge className={`text-xs ${getDifficultyColor(question.difficulty)}`}>
                      {getDifficultyLabel(question.difficulty)}
                    </Badge>
                  </div>
                </div>
              </div>
              
              <div className="grid grid-cols-2 gap-2 mb-4">
                {question.options.map((option, optionIndex) => (
                  <div 
                    key={optionIndex} 
                    className={`p-2 rounded border text-sm ${
                      optionIndex === question.correctAnswer 
                        ? 'bg-green-50 border-green-200 text-green-800' 
                        : 'bg-gray-50 border-gray-200'
                    }`}
                  >
                    {optionIndex + 1}. {option}
                  </div>
                ))}
              </div>

              <div className="flex justify-end space-x-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setSelectedQuestion(question)}
                >
                  <Eye className="w-4 h-4 mr-1" />
                  상세보기
                </Button>
                <Button variant="outline" size="sm">
                  <Edit className="w-4 h-4 mr-1" />
                  수정
                </Button>
                <Button 
                  variant="outline" 
                  size="sm" 
                  onClick={() => deleteQuestion(question.id)}
                  className="text-red-600 hover:text-red-700"
                >
                  <Trash2 className="w-4 h-4 mr-1" />
                  삭제
                </Button>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {filteredQuestions.length === 0 && (
        <Card>
          <CardContent className="text-center py-12">
            <p className="text-gray-500">검색 조건에 맞는 문제가 없습니다.</p>
          </CardContent>
        </Card>
      )}

      {selectedQuestion && (
        <QuestionDetail
          question={selectedQuestion}
          onClose={() => setSelectedQuestion(null)}
        />
      )}
    </div>
  );
};

export default QuestionBank;
