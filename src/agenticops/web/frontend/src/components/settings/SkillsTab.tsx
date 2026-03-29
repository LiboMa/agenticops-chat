import { useSkills } from "@/hooks/useSkills";
import { Card, CardBody } from "@/components/ui/Card";
import { Spinner } from "@/components/ui/Spinner";
import { Link } from "react-router-dom";

export function SkillsTab() {
  const { data: skills, isLoading } = useSkills();
  if (isLoading) return <Spinner />;

  const total = skills?.length ?? 0;
  const drafts = skills?.filter(s => s.is_draft).length ?? 0;

  return (
    <Card>
      <CardBody>
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-sm font-medium text-foreground">Agent Skills</h3>
            <p className="text-sm text-muted-foreground mt-1">
              {total} skills ({drafts} drafts)
            </p>
          </div>
          <Link
            to="/app/skills"
            className="px-4 py-2 text-sm font-medium text-primary-600 bg-primary-50 rounded-lg hover:bg-primary-100"
          >
            Manage Skills &rarr;
          </Link>
        </div>
      </CardBody>
    </Card>
  );
}
