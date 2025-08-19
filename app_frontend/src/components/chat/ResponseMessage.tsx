import React, { useState, useMemo, useRef, useEffect } from 'react';
import {
  IChatMessage,
  IMessageComponent,
  IBusinessComponent,
  IChartsComponent,
  IAnalysisComponent,
} from '@/api/chat-messages/types';
import { MessageContainer } from './MessageContainer';
import { MessageHeader } from './MessageHeader';

import { Loading } from './Loading';
import { ResponseTabs } from './ResponseTabs';
import { SummaryTabContent } from './SummaryTabContent';
import { InsightsTabContent } from './InsightsTabContent';
import { CodeTabContent } from './CodeTabContent';
import { ErrorPanel } from './ErrorPanel';
import { RESPONSE_TABS } from './constants';

interface ResponseMessageProps {
  chatId: string;
  message: IChatMessage;
  testId?: string;
}

const isMessageComponent = (component: unknown): component is IMessageComponent => {
  return !!component && typeof component === 'object' && 'enhanced_user_message' in component;
};

const isBusinessComponent = (component: unknown): component is IBusinessComponent => {
  return (
    !!component &&
    typeof component === 'object' &&
    'type' in component &&
    (component as { type?: string }).type === 'business'
  );
};

const isChartsComponent = (component: unknown): component is IChartsComponent => {
  return (
    !!component &&
    typeof component === 'object' &&
    'type' in component &&
    (component as { type?: string }).type === 'charts'
  );
};

const isAnalysisComponent = (component: unknown): component is IAnalysisComponent => {
  return (
    !!component &&
    typeof component === 'object' &&
    'type' in component &&
    (component as { type?: string }).type === 'analysis'
  );
};

export const ResponseMessage: React.FC<ResponseMessageProps> = ({ message, chatId, testId }) => {
  const [activeTab, setActiveTab] = useState(RESPONSE_TABS.SUMMARY);
  const isLoading = !!message.in_progress;

  const {
    enhancedUserMessage,
    bottomLine,
    additionalInsights,
    followUpQuestions,
    fig1_json,
    fig2_json,
    dataset,
    code,
    tabStates,
    analysisErrors,
    chartsErrors,
    businessErrors,
    analysisAttempts,
  } = useMemo(() => {
    const messageComponent = message?.components?.find(isMessageComponent);
    const businessComponent = message?.components?.find(isBusinessComponent);
    const chartsComponent = message?.components?.find(isChartsComponent);
    const analysisComponent = message?.components?.find(isAnalysisComponent);

    const enhancedUserMessage = messageComponent?.enhanced_user_message || '';
    const bottomLine = businessComponent?.bottom_line || '';
    const additionalInsights = businessComponent?.additional_insights;
    const followUpQuestions = businessComponent?.follow_up_questions;
    const fig1_json = chartsComponent?.fig1_json || '';
    const fig2_json = chartsComponent?.fig2_json || '';
    const dataset = analysisComponent?.dataset;
    const code = analysisComponent?.code || chartsComponent?.code;

    // Extract errors from components
    const hasBusinessError = businessComponent?.status === 'error';
    const hasAnalysisError = analysisComponent?.status === 'error';
    const hasChartsError = chartsComponent?.status === 'error';

    // Extract error details from metadata
    const analysisErrors =
      hasAnalysisError && analysisComponent?.metadata?.exception?.exception_history;
    const analysisAttempts = analysisComponent?.metadata?.attempts;
    const chartsErrors = hasChartsError && chartsComponent?.metadata?.exception?.exception_history;
    const businessErrors =
      hasBusinessError && businessComponent?.metadata?.exception?.exception_history;

    // Calculate tab states (loading and error indicators)
    const tabStates = {
      summary: {
        isLoading: message?.in_progress && !businessComponent && !hasBusinessError,
        hasError: hasBusinessError,
      },
      insights: {
        isLoading:
          message?.in_progress &&
          (!businessComponent || (!additionalInsights && !hasBusinessError)),
        hasError: hasBusinessError,
      },
      code: {
        isLoading:
          message?.in_progress &&
          !analysisComponent &&
          !chartsComponent?.code &&
          !hasAnalysisError &&
          !hasChartsError,
        hasError: hasAnalysisError || hasChartsError,
      },
    };

    return {
      enhancedUserMessage,
      bottomLine,
      additionalInsights,
      followUpQuestions,
      fig1_json,
      fig2_json,
      dataset,
      code,
      tabStates,
      analysisErrors,
      chartsErrors,
      businessErrors,
      analysisAttempts,
    };
  }, [message]);

  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    // Scroll to loading and to the summary bottom line when ready
    ref.current?.scrollIntoView({ behavior: 'smooth' });
  }, [isLoading, bottomLine]);

  return (
    <MessageContainer testId={testId} ref={ref}>
      <MessageHeader messageId={message.id} chatId={chatId} />

      <div className="self-stretch text-sm font-normal leading-tight">
        {/* Show enhanced user message immediately when available, even while loading */}
        {enhancedUserMessage && (
          <div className="mb-3 animate-fadeIn">
            <div className="text-muted-foreground text-xs mb-1">Analyzing your question...</div>
            <div className="font-medium">{enhancedUserMessage}</div>
          </div>
        )}

        {/* Show error if present */}
        {message?.error && (
          <div className="max-h-[300px] overflow-x-auto overflow-y-auto max-w-full animate-fadeIn">
            <span className="text-destructive text-sm">{message?.error}</span>
          </div>
        )}

        {/* Show tabs immediately, even while some content is loading */}
        {(isLoading || bottomLine || additionalInsights || code || dataset) && (
          <>
            <ResponseTabs value={activeTab} onValueChange={setActiveTab} tabStates={tabStates} />

            {activeTab === RESPONSE_TABS.SUMMARY && (
              <>
                {chartsErrors && !analysisErrors && (
                  <ErrorPanel errors={chartsErrors} componentType="Charts" />
                )}
                {isLoading && !bottomLine && !fig1_json && !fig2_json ? (
                  <div className="p-4">
                    <Loading />
                  </div>
                ) : (
                  <div className="animate-fadeIn">
                    <SummaryTabContent bottomLine={bottomLine} fig1={fig1_json} fig2={fig2_json} />
                  </div>
                )}
              </>
            )}

            {activeTab === RESPONSE_TABS.INSIGHTS && (
              <>
                {businessErrors && (
                  <ErrorPanel errors={businessErrors} componentType="Business Insights" />
                )}
                {isLoading && !additionalInsights && !followUpQuestions ? (
                  <div className="p-4">
                    <Loading />
                  </div>
                ) : (
                  <div className="animate-fadeIn">
                    <InsightsTabContent
                      additionalInsights={additionalInsights}
                      followUpQuestions={followUpQuestions}
                      chatId={chatId}
                    />
                  </div>
                )}
              </>
            )}

            {activeTab === RESPONSE_TABS.CODE && (
              <>
                {analysisErrors && (
                  <ErrorPanel
                    attempts={analysisAttempts}
                    errors={analysisErrors}
                    componentType="Analysis"
                  />
                )}
                {isLoading && !dataset && !code ? (
                  <div className="p-4">
                    <Loading />
                  </div>
                ) : (
                  <div className="animate-fadeIn">
                    <CodeTabContent dataset={dataset} code={code} />
                  </div>
                )}
              </>
            )}
          </>
        )}

        {/* Show initial loading state only if we have no content at all */}
        {isLoading && !enhancedUserMessage && !bottomLine && !additionalInsights && !code && !dataset && (
          <Loading />
        )}
      </div>
    </MessageContainer>
  );
};
