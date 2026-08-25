import { Button } from "@/components/ui/button";

export default function Home() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 p-8">
      <h1 className="text-2xl font-semibold">Understudy</h1>
      <p className="text-muted-foreground max-w-md text-center text-sm">
        Rehearse-then-dial voice recruiting on the Hunar Voice Agents API.
        Scaffold only — no feature UI yet.
      </p>
      <Button variant="outline" disabled>
        Coming soon
      </Button>
    </div>
  );
}
