/** Node-only startup dependencies must not enter the Edge instrumentation. */
export async function register(): Promise<void> {
  if (process.env.NEXT_RUNTIME === 'nodejs') {
    const { registerNodeRuntime } = await import('./instrumentation.node');
    await registerNodeRuntime();
  }
}
