import { defineMessages } from 'react-intl';

export const messages = defineMessages({
  needEditor: {
    id: 'src.components.common.PermissionTooltip.needEditor',
    defaultMessage: 'You need the editor role to do this',
  },
  needOwner: {
    id: 'src.components.common.PermissionTooltip.needOwner',
    defaultMessage: 'Only the owner or an administrator can change this',
  },
});
