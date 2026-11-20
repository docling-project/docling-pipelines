import { defineMessages } from 'react-intl';

export const messages = defineMessages({
  needEditor: {
    id: 'src.hooks.usePermissionReason.needEditor',
    defaultMessage: 'You need the editor role to do this',
  },
  needOwner: {
    id: 'src.hooks.usePermissionReason.needOwner',
    defaultMessage: 'Only the owner or an administrator can change this',
  },
});
