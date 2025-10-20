'use client';

import {
  ConsoleTemplate,
  FullScreenContainer,
  ThemeProvider,
} from '@pipecat-ai/voice-ui-kit';

import '@fontsource-variable/geist';
import '@fontsource-variable/geist-mono';

export default function Home() {
  return (
    <ThemeProvider>
      <FullScreenContainer>
        <ConsoleTemplate
          transportType="daily"
          connectParams={{
            endpoint: '/api/connect',
          }}
          noUserVideo={true}
          noBotVideo={true}
          noMetrics={false}
        />
      </FullScreenContainer>
    </ThemeProvider>
  );
}