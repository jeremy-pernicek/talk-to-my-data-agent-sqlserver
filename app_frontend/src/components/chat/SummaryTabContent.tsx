import React from 'react';
import { HeaderSection } from './HeaderSection';
import { PlotPanel } from './PlotPanel';
import { parsePlotData } from './utils';
import { useTranslation } from '@/i18n';

interface SummaryTabContentProps {
  bottomLine?: string;
  fig1: string;
  fig2: string;
}

export const SummaryTabContent: React.FC<SummaryTabContentProps> = ({ bottomLine, fig1, fig2 }) => {
  const { t } = useTranslation();
  const plot1 = parsePlotData(fig1);
  const plot2 = parsePlotData(fig2);

  // Show skeleton loaders when content is expected but not yet available
  const isLoadingBottomLine = !bottomLine && !fig1 && !fig2;
  const isLoadingCharts = bottomLine && !fig1 && !fig2;

  return (
    <div>
      {/* Show bottom line or skeleton */}
      {bottomLine ? (
        <HeaderSection title={t('Bottom line')}>{bottomLine}</HeaderSection>
      ) : isLoadingBottomLine ? (
        <div className="mb-4">
          <div className="h-4 bg-muted rounded w-24 mb-2 animate-pulse"></div>
          <div className="h-20 bg-muted rounded animate-pulse"></div>
        </div>
      ) : null}
      
      {/* Show charts or skeleton */}
      <div className="flex flex-col gap-2.5">
        {plot1 && <PlotPanel plotData={plot1} />}
        {plot2 && <PlotPanel plotData={plot2} />}
        {isLoadingCharts && (
          <>
            <div className="h-64 bg-muted rounded animate-pulse"></div>
            <div className="h-64 bg-muted rounded animate-pulse"></div>
          </>
        )}
      </div>
    </div>
  );
};
