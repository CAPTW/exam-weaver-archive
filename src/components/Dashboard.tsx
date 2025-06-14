
import React from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { FileText, Tags, Clock, TrendingUp } from 'lucide-react';
import { useQuestionStore } from '../store/questionStore';

const Dashboard = () => {
  const { questions, getQuestionsBySubject, getTotalQuestions } = useQuestionStore();
  
  const stats = [
    {
      title: '총 문제 수',
      value: getTotalQuestions(),
      icon: FileText,
      color: 'text-blue-600',
      bgColor: 'bg-blue-100'
    },
    {
      title: '과목 수',
      value: getQuestionsBySubject().size,
      icon: Tags,
      color: 'text-green-600',
      bgColor: 'bg-green-100'
    },
    {
      title: '최근 업로드',
      value: '2시간 전',
      icon: Clock,
      color: 'text-purple-600',
      bgColor: 'bg-purple-100'
    },
    {
      title: '이번 주 생성',
      value: '15개',
      icon: TrendingUp,
      color: 'text-orange-600',
      bgColor: 'bg-orange-100'
    }
  ];

  const recentActivity = [
    { action: 'PDF 업로드', file: '2024년 1회 정보처리기사.pdf', time: '2시간 전' },
    { action: '시험지 생성', file: '데이터베이스 모의고사.pdf', time: '4시간 전' },
    { action: 'PDF 업로드', file: '컴활 1급 기출문제.pdf', time: '1일 전' }
  ];

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-2xl font-bold text-gray-900 mb-2">대시보드</h2>
        <p className="text-gray-600">기출문제 은행 시스템의 현황을 한눈에 확인하세요.</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        {stats.map((stat, index) => {
          const Icon = stat.icon;
          return (
            <Card key={index} className="hover:shadow-lg transition-shadow duration-300">
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium text-gray-600">
                  {stat.title}
                </CardTitle>
                <div className={`p-2 rounded-full ${stat.bgColor}`}>
                  <Icon className={`w-4 h-4 ${stat.color}`} />
                </div>
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold text-gray-900">{stat.value}</div>
              </CardContent>
            </Card>
          );
        })}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <CardTitle>과목별 문제 분포</CardTitle>
            <CardDescription>각 과목별로 저장된 문제 수를 확인하세요.</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              {Array.from(getQuestionsBySubject()).map(([subject, count]) => (
                <div key={subject} className="flex justify-between items-center">
                  <span className="text-sm font-medium text-gray-700">{subject}</span>
                  <div className="flex items-center space-x-2">
                    <div className="w-32 bg-gray-200 rounded-full h-2">
                      <div 
                        className="bg-blue-600 h-2 rounded-full" 
                        style={{ width: `${(count / getTotalQuestions()) * 100}%` }}
                      />
                    </div>
                    <span className="text-sm text-gray-500">{count}개</span>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>최근 활동</CardTitle>
            <CardDescription>최근 PDF 업로드 및 시험지 생성 내역입니다.</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              {recentActivity.map((activity, index) => (
                <div key={index} className="flex items-center space-x-3 p-3 bg-gray-50 rounded-lg">
                  <div className="w-2 h-2 bg-blue-600 rounded-full" />
                  <div className="flex-1">
                    <p className="text-sm font-medium text-gray-900">{activity.action}</p>
                    <p className="text-xs text-gray-500">{activity.file}</p>
                  </div>
                  <span className="text-xs text-gray-400">{activity.time}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
};

export default Dashboard;
