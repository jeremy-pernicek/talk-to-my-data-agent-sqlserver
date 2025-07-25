import React, { useEffect, useRef } from 'react';

interface MessageContainerProps {
  children: React.ReactNode;
}

export const MessageContainer: React.FC<MessageContainerProps> = React.memo(({ children }) => {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current?.scrollIntoView(false);
  });
  return (
    <div
      className="p-3 bg-card rounded flex-col justify-start items-start gap-3 flex mb-2.5 mr-2"
      ref={ref}
    >
      {children}
    </div>
  );
});
