
import React, { useState } from 'react';
import { Upload, Database, FileText, Tags, Download } from 'lucide-react';
import PDFUploader from '../components/PDFUploader';
import QuestionBank from '../components/QuestionBank';
import ExamGenerator from '../components/ExamGenerator';
import Dashboard from '../components/Dashboard';
import { Button } from '@/components/ui/button';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';

const Index = () => {
  const [activeTab, setActiveTab] = useState('dashboard');

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100">
      <header className="bg-white border-b border-gray-200 shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center h-16">
            <div className="flex items-center space-x-3">
              <div className="w-10 h-10 bg-gradient-to-r from-blue-600 to-indigo-600 rounded-lg flex items-center justify-center">
                <FileText className="w-6 h-6 text-white" />
              </div>
              <div>
                <h1 className="text-xl font-bold text-gray-900">기출문제 은행 시스템</h1>
                <p className="text-sm text-gray-500">PDF 파싱 및 맞춤형 시험지 생성</p>
              </div>
            </div>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
          <TabsList className="grid w-full grid-cols-4 mb-8">
            <TabsTrigger value="dashboard" className="flex items-center space-x-2">
              <Database className="w-4 h-4" />
              <span>대시보드</span>
            </TabsTrigger>
            <TabsTrigger value="upload" className="flex items-center space-x-2">
              <Upload className="w-4 h-4" />
              <span>PDF 업로드</span>
            </TabsTrigger>
            <TabsTrigger value="bank" className="flex items-center space-x-2">
              <Tags className="w-4 h-4" />
              <span>문제은행</span>
            </TabsTrigger>
            <TabsTrigger value="generate" className="flex items-center space-x-2">
              <Download className="w-4 h-4" />
              <span>시험지 생성</span>
            </TabsTrigger>
          </TabsList>

          <TabsContent value="dashboard">
            <Dashboard />
          </TabsContent>

          <TabsContent value="upload">
            <PDFUploader />
          </TabsContent>

          <TabsContent value="bank">
            <QuestionBank />
          </TabsContent>

          <TabsContent value="generate">
            <ExamGenerator />
          </TabsContent>
        </Tabs>
      </main>
    </div>
  );
};

export default Index;
