import { IChat } from './types';
import { SidebarMenuOptionType } from '@/components/ui-custom/sidebar-menu';

export const getChatsMenu = (data: IChat[]): SidebarMenuOptionType[] => {
  const sortedChats = data?.slice().sort((a, b) => {
    const dateA = a.created_at ? new Date(a.created_at).getTime() : 0;
    const dateB = b.created_at ? new Date(b.created_at).getTime() : 0;
    return dateB - dateA;
  });

  return sortedChats?.map(c => ({
    key: c.id,
    name: c.name,
  }));
};
