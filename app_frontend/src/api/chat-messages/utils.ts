import i18n, { t } from 'i18next';

const now = new Date();

export const getChatName = () => {
  const formattedDate = new Intl.DateTimeFormat(i18n.language, {
    month: 'long',
    day: 'numeric',
  }).format(now);

  const formattedTime = new Intl.DateTimeFormat(i18n.language, {
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  }).format(now);

  return t('Chat {{formattedDate}} {{formattedTime}}', { formattedDate, formattedTime });
};
