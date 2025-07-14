import React, { useRef, useEffect, useImperativeHandle } from 'react';

import { cn } from '~/lib/utils';

type IconProps = React.ComponentProps<React.ElementType>;

type IconPropsWithBehavior<T extends IconProps> = T & {
  behavior: 'append' | 'prepend';
};

type IconComponent<T extends IconProps = IconProps> = React.ComponentType<T>;

export type TextAreaProps<T extends IconComponent = IconComponent> =
  React.TextareaHTMLAttributes<HTMLTextAreaElement> & {
    icon?: T;
    iconProps: T extends IconComponent<infer P> ? IconPropsWithBehavior<P> : never;
  };

const PromptInput = React.forwardRef<HTMLTextAreaElement, TextAreaProps>(
  (
    {
      className,
      icon,
      onKeyDown,
      iconProps: { behavior: iconBehavior, ...iconProps },
      value,
      ...props
    },
    ref
  ) => {
    const Icon = icon;
    const internalRef = useRef<HTMLTextAreaElement>(null);

    useImperativeHandle(ref, () => internalRef.current as HTMLTextAreaElement);
    useEffect(() => {
      const textarea = internalRef.current;
      if (textarea) {
        textarea.style.height = 'auto'; // Reset height to find actual value

        const textHeight = textarea.scrollHeight;
        textarea.style.height = `${textHeight}px`;
        textarea.style.overflow = textHeight > 300 ? 'auto' : 'hidden';
      }
    }, [value, ref]);

    const [isFocused, setIsFocused] = React.useState(false);
    const [isComposing, setIsComposing] = React.useState(false);

    return (
      <div
        className={cn(
          'flex border-input file:text-foreground placeholder:text-muted-foreground selection:bg-primary selection:text-primary-foreground aria-invalid:outline-destructive/60 aria-invalid:ring-destructive/20 dark:aria-invalid:outline-destructive dark:aria-invalid:ring-destructive/50 ring-ring/10 dark:ring-ring/20 dark:outline-ring/40 outline-ring/50 aria-invalid:border-destructive/60 dark:aria-invalid:border-destructive w-full rounded-md border bg-transparent px-3 py-3 text-base shadow-xs transition-[color,box-shadow] file:inline-flex file:border-0 file:bg-transparent file:text-sm file:font-medium min-w-[600px] justify-start items-center',
          isFocused &&
            'ring-4 outline-1 disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50',
          className
        )}
      >
        {Icon && iconBehavior === 'prepend' && iconProps.icon && (
          <div className={cn('w-4 h-4 mr-3 text-muted-foreground')}>{<Icon {...iconProps} />}</div>
        )}
        <textarea
          className={cn(
            'flex leading-5 box-content max-h-[300px] justify-center w-full resize-none overflow-hidden bg-transparent placeholder:text-muted-foreground file:border-0 file:bg-transparent file:text-sm file:font-medium focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50',
            className
          )}
          rows={1}
          onCompositionStart={() => setIsComposing(true)}
          onCompositionEnd={() => setIsComposing(false)}
          onKeyDown={event => {
            if (onKeyDown && !isComposing) {
              onKeyDown(event);
            }
          }}
          onFocus={() => setIsFocused(true)}
          onBlur={() => setIsFocused(false)}
          ref={internalRef}
          {...props}
        />
        {Icon && iconBehavior === 'append' && iconProps.icon && (
          <div
            className={cn(
              'w-4 ml-3 text-muted-foreground h-4 flex-col justify-center items-center inline-flex cursor-pointer'
            )}
          >
            {<Icon {...iconProps} />}
          </div>
        )}
      </div>
    );
  }
);
PromptInput.displayName = 'PromptInput';

export { PromptInput };
