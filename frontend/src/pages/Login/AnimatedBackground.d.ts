declare module '@carbon-labs/react-animated-header/es/components/AnimatedBackground/AnimatedBackground' {
  import type React from 'react';

  export interface AnimatedBackgroundProps {
    headerAnimation?: object;
    isOpen?: boolean;
  }
  const AnimatedBackground: React.FC<AnimatedBackgroundProps>;
  export default AnimatedBackground;
}
