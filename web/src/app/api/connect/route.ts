import { NextResponse } from 'next/server';

export async function POST() {
  try {
    const apiKey = process.env.PIPECAT_API_KEY;
    const apiUrl = process.env.PIPECAT_API_URL;

    if (!apiKey) {
      throw new Error('PIPECAT_API_KEY environment variable is required');
    }

    if (!apiUrl) {
      throw new Error('PIPECAT_API_URL environment variable is required');
    }

    const response = await fetch(apiUrl, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${apiKey}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        createDailyRoom: true,
      }),
    });

    if (!response.ok) {
      const body = await response.text();
      throw new Error(`Pipecat API error: ${response.status} ${response.statusText} ${body}`);
    }

    const data = await response.json();

    return NextResponse.json({
      url: data.dailyRoom,
      token: data.dailyToken,
    });
  } catch (error) {
    console.error('Error calling Pipecat API:', error);
    return NextResponse.json(
      { error: 'Failed to connect to Pipecat service' },
      { status: 500 }
    );
  }
}