import { Redirect, Route, Router, Switch } from "wouter";
import { AuthProvider, PrivateRoute } from "./auth/AuthContext";
import { AppShell } from "./components/AppShell";
import { ActivityCreatePage } from "./pages/ActivityCreatePage";
import { ActivityEditPage } from "./pages/ActivityEditPage";
import { ActivitiesPage } from "./pages/ActivitiesPage";
import { AssessmentReviewPage } from "./pages/AssessmentReviewPage";
import { BlueprintPage } from "./pages/BlueprintPage";
import { LoginPage } from "./pages/LoginPage";
import {
  SubmissionProgressPage,
  SubmissionStartPage,
} from "./pages/SubmissionPage";

export function AppRoutes() {
  return (
    <AuthProvider>
      <Switch>
        <Route path="/login"><LoginPage /></Route>
        <Route path="/activities">
          <PrivateRoute><AppShell><ActivitiesPage /></AppShell></PrivateRoute>
        </Route>
        <Route path="/activities/new">
          <PrivateRoute><AppShell><ActivityCreatePage /></AppShell></PrivateRoute>
        </Route>
        <Route path="/activities/:activityId/edit">
          <PrivateRoute><AppShell><ActivityEditPage /></AppShell></PrivateRoute>
        </Route>
        <Route path="/activities/:activityId/blueprint">
          <PrivateRoute><AppShell><BlueprintPage /></AppShell></PrivateRoute>
        </Route>
        <Route path="/activities/:activityId/submission">
          <PrivateRoute><AppShell><SubmissionStartPage /></AppShell></PrivateRoute>
        </Route>
        <Route path="/submissions/:submissionId/review">
          <PrivateRoute><AppShell><AssessmentReviewPage /></AppShell></PrivateRoute>
        </Route>
        <Route path="/submissions/:submissionId">
          <PrivateRoute><AppShell><SubmissionProgressPage /></AppShell></PrivateRoute>
        </Route>
        <Route><Redirect to="/activities" replace /></Route>
      </Switch>
    </AuthProvider>
  );
}

export default function App() {
  return (
    <Router>
      <AppRoutes />
    </Router>
  );
}
