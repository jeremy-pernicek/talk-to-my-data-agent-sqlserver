import React from 'react';
import { IDataset as DatasetType } from '@/api/chat-messages/types';
import { CollapsiblePanel } from './CollapsiblePanel';
import { AnalystDatasetTable } from './AnalystDatasetTable';
import { useTranslation } from '@/i18n';
// @ts-expect-error ???
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
// @ts-expect-error ???
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';
import './MarkdownContent.css';

interface CodeTabContentProps {
  dataset?: DatasetType | null;
  code?: string | null;
}

export const CodeTabContent: React.FC<CodeTabContentProps> = ({ dataset, code }) => {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-2.5">
      {/* <InfoText>
        DataRobot generates additional content based on your original question.
      </InfoText> */}
      {dataset && (
        <CollapsiblePanel header={t('Dataset')}>
          <AnalystDatasetTable records={dataset?.data_records} />
        </CollapsiblePanel>
      )}
      {code && (
        <CollapsiblePanel header={t('Code')}>
          <div className="markdown-content">
            <SyntaxHighlighter
              language="python"
              style={oneDark}
              customStyle={{
                margin: 0,
                borderRadius: '4px',
              }}
              wrapLongLines={true}
              showLineNumbers={true}
            >
              {code}
            </SyntaxHighlighter>
          </div>
        </CollapsiblePanel>
      )}
    </div>
  );
};
